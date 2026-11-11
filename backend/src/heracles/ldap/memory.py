"""In-memory :class:`DirectoryClient` for tests.

Behaviour mirrors a real server where it matters to callers:

* parents must exist before children are added (except the base entry);
* ``search`` validates its base eagerly and enforces ``size_limit``;
* ``modify`` is atomic (all changes or none);
* ``delete`` refuses non-leaf entries unless ``recursive``;
* ``rename`` moves the whole subtree and swaps the RDN value.

Everything returned is a copy; mutating a result never alters the directory.
Entries added without their RDN value get it added automatically.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    Attributes,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
    SizeLimitExceededError,
)
from heracles.ldap.filter import Filter, matches, parse_filter
from heracles.ldap.ldif import dump_ldif, parse_ldif
from heracles.schema import names as schema

_DEFAULT_SCHEMA: frozenset[str] = frozenset(
    {v.lower() for v in schema.CORE_OBJECT_CLASSES}
    | {
        v.lower()
        for v in (
            schema.STD_OC.INET_ORG_PERSON,
            schema.STD_OC.ORGANIZATIONAL_PERSON,
            schema.STD_OC.PERSON,
            schema.STD_OC.GROUP_OF_NAMES,
            schema.STD_OC.POSIX_GROUP,
            schema.STD_OC.ORGANIZATIONAL_ROLE,
            schema.STD_OC.ORGANIZATIONAL_UNIT,
            schema.STD_OC.ORGANIZATION,
            schema.STD_OC.LOCALITY,
            schema.STD_OC.COUNTRY,
            schema.STD_OC.DC_OBJECT,
            schema.STD_OC.DOMAIN,
            schema.STD_OC.POSIX_ACCOUNT,
            schema.STD_OC.SHADOW_ACCOUNT,
            schema.STD_OC.PUBLIC_KEY,
            schema.STD_OC.SUDO_ROLE,
            schema.STD_OC.PWD_POLICY,
            schema.STD_OC.TOP,
        )
    }
)


def _copy_attrs(attrs: Mapping[str, Sequence[bytes]]) -> Attributes:
    """Copy attributes, merging keys that differ only by case."""
    out: Attributes = {}
    lower: dict[str, str] = {}
    for name, values in attrs.items():
        key = lower.setdefault(name.lower(), name)
        bucket = out.setdefault(key, [])
        for value in values:
            if value not in bucket:
                bucket.append(bytes(value))
    return out


def _find_key(attrs: Attributes, name: str) -> str | None:
    lname = name.lower()
    for key in attrs:
        if key.lower() == lname:
            return key
    return None


def _rdn_pair(rdn: str) -> tuple[str, str]:
    """Return ``(attr, unescaped value)`` of a single-valued RDN."""
    attr, sep, value = rdn.partition("=")
    if not sep or not attr.strip():
        raise DirectoryError(f"invalid RDN: {rdn!r}")
    out: list[str] = []
    escaped = False
    for ch in value.strip():
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            out.append(ch)
    return attr.strip(), "".join(out)


class MemoryDirectory:
    """Thread-safe in-memory directory implementing ``DirectoryClient``."""

    def __init__(
        self,
        base_dn: str,
        *,
        object_classes: Iterable[str] | None = None,
        passwords: Mapping[str, str] | None = None,
    ) -> None:
        self._base_dn = base_dn
        self._entries: dict[str, Entry] = {}
        self._passwords: dict[str, str] = {
            dnlib.normalize(k): v for k, v in (passwords or {}).items()
        }
        self._schema: set[str] = {c.lower() for c in (object_classes or _DEFAULT_SCHEMA)}
        self._lock = threading.RLock()

    # -- construction helpers -------------------------------------------------

    @classmethod
    def from_ldif(cls, text: str, base_dn: str | None = None) -> MemoryDirectory:
        """Build a directory from LDIF text.

        Entries may appear in any order. ``base_dn`` defaults to the shallowest
        entry of the LDIF.
        """
        records = parse_ldif(text)
        if base_dn is None:
            if not records:
                raise ValueError("cannot infer base_dn from empty LDIF")
            base_dn = min(records, key=lambda e: dnlib.depth(e.dn)).dn
        directory = cls(base_dn)
        for entry in sorted(records, key=lambda e: dnlib.depth(e.dn)):
            directory.add(entry.dn, entry.attrs)
        return directory

    def to_ldif(self, base: str | None = None) -> str:
        """Dump the directory (or a subtree) as LDIF, parents first."""
        with self._lock:
            entries = [
                e for e in self._entries.values() if base is None or dnlib.is_descendant(e.dn, base)
            ]
            return dump_ldif(Entry(e.dn, _copy_attrs(e.attrs)) for e in entries)

    def set_password(self, dn: str, password: str) -> None:
        """Register a cleartext password used by :meth:`check_password`."""
        with self._lock:
            self._passwords[dnlib.normalize(dn)] = password

    def set_schema_object_classes(self, names: Iterable[str]) -> None:
        """Replace the objectClass names reported by the fake schema."""
        with self._lock:
            self._schema = {n.lower() for n in names}

    def dns(self) -> list[str]:
        """All DNs currently stored (insertion order)."""
        with self._lock:
            return [e.dn for e in self._entries.values()]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, dn: object) -> bool:
        return isinstance(dn, str) and dnlib.normalize(dn) in self._entries

    # -- DirectoryClient ------------------------------------------------------

    @property
    def base_dn(self) -> str:
        return self._base_dn

    def search(
        self,
        base: str,
        filterstr: str = "(objectClass=*)",
        scope: Scope = Scope.SUBTREE,
        attrs: Sequence[str] | None = None,
        *,
        size_limit: int = 0,
        page_size: int = 500,
    ) -> Iterator[Entry]:
        del page_size
        flt: Filter = parse_filter(filterstr)
        nbase = dnlib.normalize(base)
        with self._lock:
            if nbase not in self._entries:
                raise NoSuchObjectError(base)
            results: list[Entry] = []
            for key, entry in self._entries.items():
                if not self._in_scope(key, nbase, scope) or not matches(entry, flt):
                    continue
                if size_limit and len(results) >= size_limit:
                    raise SizeLimitExceededError(f"more than {size_limit} entries")
                results.append(self._project(entry, attrs))
        return iter(results)

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        with self._lock:
            entry = self._entries.get(dnlib.normalize(dn))
            return self._project(entry, attrs) if entry is not None else None

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        key = dnlib.normalize(dn)
        parts = dnlib.split(dn)
        if not parts:
            raise DirectoryError("empty DN")
        with self._lock:
            if key in self._entries:
                raise AlreadyExistsError(dn)
            parent = dnlib.parent(dn)
            if key != dnlib.normalize(self._base_dn) and (
                parent is None or dnlib.normalize(parent) not in self._entries
            ):
                raise NoSuchObjectError(f"parent of {dn} does not exist")
            new_attrs = _copy_attrs(attrs)
            self._ensure_rdn_value(new_attrs, parts[0])
            self._entries[key] = Entry(dn=dn, attrs=new_attrs)

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        key = dnlib.normalize(dn)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise NoSuchObjectError(dn)
            work = _copy_attrs(entry.attrs)
            for change in changes:
                self._apply(work, change)
            rdn_attr, rdn_value = _rdn_pair(dnlib.rdn(entry.dn))
            rdn_key = _find_key(work, rdn_attr)
            wanted = rdn_value.casefold()
            if rdn_key is None or not any(
                v.decode("utf-8", errors="replace").casefold() == wanted for v in work[rdn_key]
            ):
                raise DirectoryError("modification would remove the RDN value")
            entry.attrs = work

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        key = dnlib.normalize(dn)
        with self._lock:
            if key not in self._entries:
                raise NoSuchObjectError(dn)
            below = [k for k in self._entries if k != key and k.endswith("," + key)]
            if below and not recursive:
                raise DirectoryError(f"{dn} has subordinate entries")
            for k in below:
                del self._entries[k]
            del self._entries[key]
            self._passwords.pop(key, None)

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        key = dnlib.normalize(dn)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise NoSuchObjectError(dn)
            superior = new_superior if new_superior is not None else dnlib.parent(dn)
            if superior is None:
                raise DirectoryError("cannot rename a root entry without a new superior")
            if dnlib.normalize(superior) not in self._entries:
                raise NoSuchObjectError(superior)
            if dnlib.is_descendant(superior, dn):
                raise DirectoryError("cannot move an entry below itself")
            new_dn = dnlib.join(new_rdn, superior)
            new_key = dnlib.normalize(new_dn)
            if new_key != key and new_key in self._entries:
                raise AlreadyExistsError(new_dn)

            old_attr, old_value = _rdn_pair(dnlib.rdn(entry.dn))
            new_attr, new_value = _rdn_pair(new_rdn)
            attrs = _copy_attrs(entry.attrs)
            old_key = _find_key(attrs, old_attr)
            if old_key is not None:
                attrs[old_key] = [
                    v
                    for v in attrs[old_key]
                    if v.decode("utf-8", errors="replace").casefold() != old_value.casefold()
                ]
                if not attrs[old_key]:
                    del attrs[old_key]
            self._ensure_rdn_value(attrs, f"{new_attr}={new_value}")

            suffix = "," + key
            rebuilt: dict[str, Entry] = {}
            for k, e in self._entries.items():
                if k == key:
                    rebuilt[new_key] = Entry(new_dn, attrs)
                elif k.endswith(suffix):
                    relative = dnlib.split(e.dn)[: dnlib.depth(e.dn) - dnlib.depth(dn)]
                    child_dn = dnlib.join(",".join(relative), new_dn)
                    rebuilt[dnlib.normalize(child_dn)] = Entry(child_dn, e.attrs)
                else:
                    rebuilt[k] = e
            self._entries = rebuilt
            if key in self._passwords:
                self._passwords[new_key] = self._passwords.pop(key)
            return new_dn

    def check_password(self, dn: str, password: str) -> bool:
        if not password:
            return False
        with self._lock:
            key = dnlib.normalize(dn)
            entry = self._entries.get(key)
            if entry is None:
                return False
            if key in self._passwords:
                return self._passwords[key] == password
            for value in entry.get("userPassword"):
                text = value.decode("utf-8", errors="replace")
                if text.upper().startswith("{CLEARTEXT}"):
                    text = text[len("{CLEARTEXT}") :]
                if text == password:
                    return True
            return False

    def schema_object_classes(self) -> set[str]:
        with self._lock:
            return set(self._schema)

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _in_scope(key: str, nbase: str, scope: Scope) -> bool:
        if scope is Scope.BASE:
            return key == nbase
        if scope is Scope.ONE:
            return key.endswith("," + nbase) and dnlib.depth(key) == dnlib.depth(nbase) + 1
        return key == nbase or key.endswith("," + nbase)

    @staticmethod
    def _project(entry: Entry, attrs: Sequence[str] | None) -> Entry:
        if attrs is None or "*" in attrs:
            return Entry(entry.dn, _copy_attrs(entry.attrs))
        wanted = {a.lower() for a in attrs}
        return Entry(
            entry.dn,
            {k: [bytes(v) for v in vals] for k, vals in entry.attrs.items() if k.lower() in wanted},
        )

    @staticmethod
    def _ensure_rdn_value(attrs: Attributes, rdn: str) -> None:
        name, value = _rdn_pair(rdn)
        key = _find_key(attrs, name) or name
        bucket = attrs.setdefault(key, [])
        raw = value.encode("utf-8")
        if not any(
            v.decode("utf-8", errors="replace").casefold() == value.casefold() for v in bucket
        ):
            bucket.append(raw)

    @staticmethod
    def _apply(work: Attributes, change: Modification) -> None:
        key = _find_key(work, change.attr)
        values = [bytes(v) for v in change.values]
        if change.op == "add":
            if not values:
                raise DirectoryError(f"add of {change.attr} without values")
            if key is None:
                work[change.attr] = list(dict.fromkeys(values))
                return
            for v in values:
                if v in work[key]:
                    raise DirectoryError(f"value already exists for {change.attr}")
                work[key].append(v)
        elif change.op == "replace":
            if not values:
                if key is not None:
                    del work[key]
            else:
                work[key or change.attr] = list(dict.fromkeys(values))
        else:
            if key is None:
                raise DirectoryError(f"no such attribute: {change.attr}")
            if not values:
                del work[key]
                return
            for v in values:
                if v not in work[key]:
                    raise DirectoryError(f"no such value for {change.attr}")
                work[key].remove(v)
            if not work[key]:
                del work[key]
