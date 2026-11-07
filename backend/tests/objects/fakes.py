"""Minimal dict-backed DirectoryClient used by the object layer tests."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)


def _parse(flt: str, pos: int = 0) -> tuple[Any, int]:
    assert flt[pos] == "(", flt
    if flt[pos + 1] in "&|!":
        op = flt[pos + 1]
        pos += 2
        items: list[Any] = []
        while flt[pos] == "(":
            node, pos = _parse(flt, pos)
            items.append(node)
        assert flt[pos] == ")"
        return (op, items), pos + 1
    end = pos + 1
    while flt[end] != ")":
        end += 1
    attr, _, value = flt[pos + 1 : end].partition("=")
    return ("=", attr, value), end + 1


def _unescape(value: str) -> str:
    return re.sub(r"\\([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), value)


def _match(node: Any, entry: Entry) -> bool:
    op = node[0]
    if op == "&":
        return all(_match(n, entry) for n in node[1])
    if op == "|":
        return any(_match(n, entry) for n in node[1])
    if op == "!":
        return not _match(node[1][0], entry)
    _, attr, value = node
    have = [v.decode("utf-8").lower() for v in entry.get(attr)]
    if value == "*":
        return bool(have)
    parts = [_unescape(p).lower() for p in re.split(r"(?<!\\)\*", value)] if "*" in value else None
    if parts is None:
        return _unescape(value).lower() in have
    # substring: raw '*' may only come from unescaped stars
    pattern = ".*".join(re.escape(p) for p in parts)
    return any(re.fullmatch(pattern, h, re.DOTALL) for h in have)


class FakeDirectory:
    """In-memory directory implementing the ``DirectoryClient`` protocol."""

    def __init__(self, base_dn: str = "dc=example,dc=com", classes: set[str] | None = None) -> None:
        self._base = base_dn
        self.entries: dict[str, Entry] = {}
        self.classes: set[str] = classes if classes is not None else set()
        self.log: list[tuple[str, Any]] = []
        self.searches: list[tuple[str, str, Scope]] = []

    @property
    def base_dn(self) -> str:
        return self._base

    def put(self, dn: str, **attrs: Sequence[str] | str) -> Entry:
        """Insert a test entry (string values are UTF-8 encoded)."""
        data = {
            k: [x.encode() for x in ([v] if isinstance(v, str) else v)] for k, v in attrs.items()
        }
        entry = Entry(dn, data)
        self.entries[dnlib.normalize(dn)] = entry
        return entry

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
        self.searches.append((base, filterstr, scope))
        nbase = dnlib.normalize(base)
        if nbase not in self.entries:
            raise NoSuchObjectError(base)
        tree, _ = _parse(filterstr)
        for key, entry in list(self.entries.items()):
            if scope == Scope.BASE:
                inside = key == nbase
            elif scope == Scope.ONE:
                par = dnlib.parent(key)
                inside = par is not None and dnlib.normalize(par) == nbase
            else:
                inside = dnlib.is_descendant(key, nbase)
            if inside and _match(tree, entry):
                yield Entry(entry.dn, {k: list(v) for k, v in entry.attrs.items()})

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        entry = self.entries.get(dnlib.normalize(dn))
        if entry is None:
            return None
        return Entry(entry.dn, {k: list(v) for k, v in entry.attrs.items()})

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        key = dnlib.normalize(dn)
        if key in self.entries:
            raise AlreadyExistsError(dn)
        self.log.append(("add", (dn, {k: list(v) for k, v in attrs.items()})))
        self.entries[key] = Entry(dn, {k: list(v) for k, v in attrs.items()})

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        entry = self.entries.get(dnlib.normalize(dn))
        if entry is None:
            raise NoSuchObjectError(dn)
        self.log.append(("modify", (dn, list(changes))))
        for change in changes:
            name = next((k for k in entry.attrs if k.lower() == change.attr.lower()), change.attr)
            current = entry.attrs.get(name, [])
            if change.op == "add":
                entry.attrs[name] = [*current, *change.values]
            elif change.op == "replace":
                entry.attrs[name] = list(change.values)
            elif not change.values:
                entry.attrs.pop(name, None)
            else:
                entry.attrs[name] = [v for v in current if v not in change.values]
            if not entry.attrs.get(name):
                entry.attrs.pop(name, None)

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        key = dnlib.normalize(dn)
        if key not in self.entries:
            raise NoSuchObjectError(dn)
        self.log.append(("delete", dn))
        del self.entries[key]

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        key = dnlib.normalize(dn)
        entry = self.entries.get(key)
        if entry is None:
            raise NoSuchObjectError(dn)
        superior = new_superior if new_superior is not None else (dnlib.parent(dn) or "")
        new_dn = f"{new_rdn},{superior}" if superior else new_rdn
        if dnlib.normalize(new_dn) in self.entries and dnlib.normalize(new_dn) != key:
            raise AlreadyExistsError(new_dn)
        self.log.append(("rename", (dn, new_rdn, new_superior)))
        old_attr, _, old_val = dnlib.rdn(dn).partition("=")
        new_attr, _, new_val = new_rdn.partition("=")
        old_name = next((k for k in entry.attrs if k.lower() == old_attr.lower()), old_attr)
        entry.attrs[old_name] = [v for v in entry.attrs.get(old_name, []) if v.decode() != old_val]
        entry.attrs.setdefault(new_attr, []).append(new_val.encode())
        entry.attrs = {k: v for k, v in entry.attrs.items() if v}
        del self.entries[key]
        entry.dn = new_dn
        self.entries[dnlib.normalize(new_dn)] = entry
        return new_dn

    def check_password(self, dn: str, password: str) -> bool:
        return False

    def schema_object_classes(self) -> set[str]:
        return {c.lower() for c in self.classes}

    def modifications(self) -> list[list[Modification]]:
        """All modify calls, in order."""
        return [v[1] for k, v in self.log if k == "modify"]
