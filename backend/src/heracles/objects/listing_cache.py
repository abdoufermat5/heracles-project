"""Short-lived snapshots of listing results, so paging does not repeat the search.

A listing searches the directory, drops what the caller may not read and sorts the
whole result before slicing one page. Paging through thousands of entries would redo
that for every page, so the filtered and sorted entry list is kept for a few seconds
and later pages are cut from it.

The cache is process-local (workers do not share it) and bounded: snapshots expire
after :data:`LISTING_TTL` seconds and at most :data:`MAX_SNAPSHOTS` are kept, the least
recently used one being dropped first. Every snapshot belongs to one owner (the
session), because the ACL filtering baked into it differs between users.

Staleness: a write made through the same session clears that session's snapshots,
and so does a change of its ACL resolution. Writes made by other sessions are not
seen until the snapshot expires or the user reloads the first page, which always
searches the directory again.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from heracles.ldap.client import Entry, Scope

#: Seconds a snapshot stays usable for the later pages of a listing.
LISTING_TTL = 30.0
#: Snapshots kept in total (all owners); bounds the memory used.
MAX_SNAPSHOTS = 64


class ListingKey(NamedTuple):
    """What identifies one listing result."""

    owner: str
    type_name: str
    #: Normalised search base.
    base: str
    scope: Scope
    query: str
    sort: str
    descending: bool
    extra_attrs: tuple[str, ...]
    #: Extra caller-supplied LDAP filter (empty: none).
    extra_filter: str = ""


@dataclass(frozen=True, slots=True)
class _Snapshot:
    entries: Sequence[Entry]
    expires: float
    #: Identity of the owner's ACL resolution the entries were filtered with.
    version: object


class ListingCache:
    """Thread-safe LRU of listing snapshots with a time to live."""

    def __init__(
        self,
        *,
        ttl: float = LISTING_TTL,
        max_snapshots: int = MAX_SNAPSHOTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max = max(1, max_snapshots)
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[ListingKey, _Snapshot] = OrderedDict()

    def get(self, key: ListingKey, version: object) -> Sequence[Entry] | None:
        """The fresh snapshot of ``key`` made under ``version``, if any."""
        with self._lock:
            snap = self._items.get(key)
            if snap is None:
                return None
            if snap.expires <= self._clock() or snap.version is not version:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return snap.entries

    def put(self, key: ListingKey, version: object, entries: Sequence[Entry]) -> None:
        with self._lock:
            now = self._clock()
            self._items[key] = _Snapshot(tuple(entries), now + self._ttl, version)
            self._items.move_to_end(key)
            for stale in [k for k, s in self._items.items() if s.expires <= now]:
                del self._items[stale]
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def invalidate(self, owner: str) -> None:
        """Forget every snapshot of one owner."""
        with self._lock:
            for key in [k for k in self._items if k.owner == owner]:
                del self._items[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass(frozen=True, slots=True)
class ListingScope:
    """A cache bound to one owner and one ACL resolution, as an object service uses it."""

    cache: ListingCache
    owner: str
    #: Identity of the owner's current ACL resolution; snapshots made under another one
    #: are ignored (an ACL change alters what the owner may see).
    version: object

    def key(
        self,
        type_name: str,
        base: str,
        scope: Scope,
        query: str,
        sort: str,
        descending: bool,
        extra_attrs: Sequence[str],
        extra_filter: str = "",
    ) -> ListingKey:
        return ListingKey(
            self.owner,
            type_name,
            base,
            scope,
            query,
            sort,
            descending,
            tuple(extra_attrs),
            extra_filter,
        )

    def get(self, key: ListingKey) -> Sequence[Entry] | None:
        return self.cache.get(key, self.version)

    def put(self, key: ListingKey, entries: Sequence[Entry]) -> None:
        self.cache.put(key, self.version, entries)


__all__ = [
    "LISTING_TTL",
    "MAX_SNAPSHOTS",
    "ListingCache",
    "ListingKey",
    "ListingScope",
]
