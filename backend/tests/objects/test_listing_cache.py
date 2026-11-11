"""Listing snapshot cache: expiry, bounded size, per-owner invalidation, ACL version."""

from __future__ import annotations

from heracles.ldap.client import Entry, Scope
from heracles.objects.listing_cache import ListingCache, ListingKey

VERSION = object()


def key(owner: str = "s1", query: str = "") -> ListingKey:
    return ListingKey(owner, "user", "dc=x", Scope.SUBTREE, query, "uid", False, ())


def entries(*uids: str) -> list[Entry]:
    return [Entry(f"uid={u},dc=x", {"uid": [u.encode()]}) for u in uids]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_snapshot_expires_after_the_ttl() -> None:
    clock = Clock()
    cache = ListingCache(ttl=30, clock=clock)
    cache.put(key(), VERSION, entries("a"))
    clock.now = 29
    assert cache.get(key(), VERSION) is not None
    clock.now = 30
    assert cache.get(key(), VERSION) is None
    assert len(cache) == 0


def test_least_recently_used_snapshot_is_evicted() -> None:
    cache = ListingCache(max_snapshots=2)
    cache.put(key(query="a"), VERSION, entries("a"))
    cache.put(key(query="b"), VERSION, entries("b"))
    assert cache.get(key(query="a"), VERSION) is not None  # "b" is now the oldest
    cache.put(key(query="c"), VERSION, entries("c"))
    assert cache.get(key(query="b"), VERSION) is None
    assert cache.get(key(query="a"), VERSION) is not None
    assert cache.get(key(query="c"), VERSION) is not None


def test_invalidation_is_per_owner() -> None:
    cache = ListingCache()
    cache.put(key("s1"), VERSION, entries("a"))
    cache.put(key("s1", "q"), VERSION, entries("a"))
    cache.put(key("s2"), VERSION, entries("b"))
    cache.invalidate("s1")
    assert cache.get(key("s1"), VERSION) is None
    assert cache.get(key("s1", "q"), VERSION) is None
    assert cache.get(key("s2"), VERSION) is not None


def test_snapshot_made_under_another_acl_resolution_is_ignored() -> None:
    cache = ListingCache()
    cache.put(key(), VERSION, entries("a"))
    assert cache.get(key(), object()) is None
