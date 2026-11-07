"""Test doubles: a dict-backed DirectoryClient with a small LDAP filter matcher."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)

Predicate = Callable[[Entry], bool]


def _unescape(value: str) -> str:
    return re.sub(r"\\([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), value)


def _parse(text: str, pos: int) -> tuple[Predicate, int]:
    if text[pos] != "(":
        raise ValueError(f"bad filter {text!r} at {pos}")
    pos += 1
    op = text[pos]
    if op in "&|":
        subs: list[Predicate] = []
        pos += 1
        while text[pos] == "(":
            sub, pos = _parse(text, pos)
            subs.append(sub)
        if text[pos] != ")":
            raise ValueError(f"bad filter {text!r}")
        if op == "&":
            return (lambda e: all(s(e) for s in subs)), pos + 1
        return (lambda e: any(s(e) for s in subs)), pos + 1
    if op == "!":
        inner, pos = _parse(text, pos + 1)
        if text[pos] != ")":
            raise ValueError(f"bad filter {text!r}")
        return (lambda e: not inner(e)), pos + 1
    end = pos
    while text[end] != ")":
        end += 1
    body = text[pos:end]
    name, sep, raw = body.partition("=")
    if not sep:
        raise ValueError(f"bad filter item {body!r}")
    if raw == "*":
        return (lambda e: bool(e.get(name))), end + 1
    if "*" in raw:
        pattern = re.compile(
            ".*".join(re.escape(_unescape(p)) for p in raw.split("*")) + r"\Z", re.IGNORECASE
        )
        return (lambda e: any(pattern.match(v) for v in e.texts(name))), end + 1
    wanted = _unescape(raw).lower()
    return (lambda e: any(v.lower() == wanted for v in e.texts(name))), end + 1


def compile_filter(text: str) -> Predicate:
    """Compile an LDAP filter (equality, presence, substring, &, |, !)."""
    predicate, end = _parse(text.strip(), 0)
    if end != len(text.strip()):
        raise ValueError(f"trailing characters in filter {text!r}")
    return predicate


class MemoryClient:
    """Minimal in-memory DirectoryClient (tests only)."""

    def __init__(self, base_dn: str) -> None:
        self._base = base_dn
        self._entries: dict[str, Entry] = {}

    @property
    def base_dn(self) -> str:
        return self._base

    def put(self, dn: str, **attrs: Sequence[str]) -> Entry:
        """Create or replace an entry from text attributes."""
        entry = Entry(dn, {k: [v.encode() for v in vs] for k, vs in attrs.items()})
        self._entries[dnlib.normalize(dn)] = entry
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
        nbase = dnlib.normalize(base)
        if nbase not in self._entries:
            raise NoSuchObjectError(base)
        predicate = compile_filter(filterstr)
        for key, entry in list(self._entries.items()):
            if scope is Scope.BASE and key != nbase:
                continue
            if scope is Scope.ONE and dnlib.normalize(dnlib.parent(key) or "") != nbase:
                continue
            if scope is Scope.SUBTREE and not dnlib.is_descendant(key, nbase):
                continue
            if predicate(entry):
                yield entry

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        return self._entries.get(dnlib.normalize(dn))

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        key = dnlib.normalize(dn)
        if key in self._entries:
            raise AlreadyExistsError(dn)
        self._entries[key] = Entry(dn, {k: list(v) for k, v in attrs.items()})

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        raise NotImplementedError

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        del self._entries[dnlib.normalize(dn)]

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        raise NotImplementedError

    def check_password(self, dn: str, password: str) -> bool:
        return False

    def schema_object_classes(self) -> set[str]:
        return set()
