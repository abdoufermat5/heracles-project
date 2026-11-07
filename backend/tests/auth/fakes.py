"""Test double for ``DirectoryClient`` (dict-backed, minimal filter support)."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)


def _unescape(value: str) -> bytes:
    out = bytearray()
    i = 0
    raw = value.encode()
    while i < len(raw):
        if (
            raw[i] == 0x5C
            and i + 2 < len(raw) + 0
            and re.fullmatch(rb"[0-9a-fA-F]{2}", raw[i + 1 : i + 3])
        ):
            out.append(int(raw[i + 1 : i + 3], 16))
            i += 3
        else:
            out.append(raw[i])
            i += 1
    return bytes(out)


def _split_filters(body: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(body):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                parts.append(body[start : i + 1])
    return parts


def matches(entry: Entry, flt: str) -> bool:
    """Evaluate ``(attr=value)``, ``(attr=*)`` and ``(&...)`` filters."""
    flt = flt.strip()
    if not (flt.startswith("(") and flt.endswith(")")):
        raise ValueError(f"bad filter: {flt}")
    inner = flt[1:-1]
    if inner.startswith("&"):
        return all(matches(entry, sub) for sub in _split_filters(inner[1:]))
    attr, _, value = inner.partition("=")
    if value == "*":
        return bool(entry.get(attr))
    wanted = _unescape(value).lower()
    return any(v.lower() == wanted for v in entry.get(attr))


class FakeDirectory:
    """Minimal in-memory ``DirectoryClient``."""

    def __init__(self, base_dn: str = "dc=example,dc=com") -> None:
        self._base = base_dn
        self.entries: dict[str, Entry] = {}
        self.passwords: dict[str, str] = {}
        self.bind_attempts: list[tuple[str, str]] = []
        self.add(base_dn, {"objectClass": [b"dcObject"]})

    @property
    def base_dn(self) -> str:
        return self._base

    def add_user(
        self,
        uid: str,
        password: str,
        *,
        mail: str | None = None,
        cn: str | None = None,
        user_password: str | None = None,
    ) -> str:
        dn = f"uid={uid},ou=people,{self._base}"
        attrs: dict[str, list[bytes]] = {
            "objectClass": [b"inetOrgPerson"],
            "uid": [uid.encode()],
            "cn": [(cn or uid).encode()],
            "sn": [uid.encode()],
        }
        if mail:
            attrs["mail"] = [mail.encode()]
        if user_password is not None:
            attrs["userPassword"] = [user_password.encode()]
        self.add(dn, attrs)
        self.passwords[dnlib.normalize(dn)] = password
        return dn

    # -- DirectoryClient -------------------------------------------------------------------------
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
        if dnlib.normalize(base) not in {dnlib.normalize(k) for k in self.entries}:
            raise NoSuchObjectError(base)
        nbase = dnlib.normalize(base)
        for entry in list(self.entries.values()):
            ndn = dnlib.normalize(entry.dn)
            if scope is Scope.BASE and ndn != nbase:
                continue
            if scope is Scope.ONE and dnlib.normalize(dnlib.parent(entry.dn) or "") != nbase:
                continue
            if scope is Scope.SUBTREE and not dnlib.is_descendant(entry.dn, base):
                continue
            if matches(entry, filterstr):
                yield entry

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        for key, entry in self.entries.items():
            if dnlib.normalize(key) == dnlib.normalize(dn):
                return entry
        return None

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        if self.get(dn) is not None:
            raise AlreadyExistsError(dn)
        self.entries[dn] = Entry(dn, {k: list(v) for k, v in attrs.items()})

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        entry = self.get(dn)
        if entry is None:
            raise NoSuchObjectError(dn)
        for change in changes:
            if change.op == "replace":
                entry.attrs[change.attr] = list(change.values)
            elif change.op == "add":
                entry.attrs.setdefault(change.attr, []).extend(change.values)
            else:
                entry.attrs.pop(change.attr, None)

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        self.entries.pop(dn, None)

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        raise NotImplementedError

    def check_password(self, dn: str, password: str) -> bool:
        self.bind_attempts.append((dn, password))
        stored = self.passwords.get(dnlib.normalize(dn))
        return stored is not None and password != "" and stored == password

    def schema_object_classes(self) -> set[str]:
        return {"inetorgperson", "person"}
