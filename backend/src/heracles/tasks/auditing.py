"""Audit the directory writes of scheduled task runners.

A runner gets an :class:`AuditingDirectory` instead of the bare client: every add, modify,
delete and rename it makes is recorded as an audit event (no author DN, ``source: task
<runner>``). Task bookkeeping (``hrcTasks*`` attributes and entries) and the audit log itself
are not recorded, so a retention purge does not log one event per purged event.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from heracles.core.audit import AUDIT_RDN, AuditSink
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, Entry, Modification, Scope

__all__ = ["DEFAULT_HIDDEN", "AuditingDirectory"]

#: Values longer than this are cut in the recorded attribute lines.
MAX_VALUE_LENGTH = 256
#: Prefix of the task bookkeeping attributes and object classes (not audited).
BOOKKEEPING_PREFIX = "hrctasks"
DEFAULT_HIDDEN = ("userPassword",)


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return "<binary>"


def _describe(name: str, values: Sequence[bytes], hidden: set[str], op: str = "") -> str:
    prefix = f"{op} " if op else ""
    if name.lower() in hidden:
        return f"{prefix}{name}: ***"
    if not values:
        return f"{prefix}{name}: (removed)"
    text = f"{prefix}{name}: " + ", ".join(_text(v) for v in values)
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 3] + "..."


def _bookkeeping(name: str) -> bool:
    return name.lower().startswith(BOOKKEEPING_PREFIX)


class AuditingDirectory:
    """A :class:`DirectoryClient` recording the writes made through it."""

    def __init__(
        self,
        inner: DirectoryClient,
        sink: AuditSink,
        *,
        source: str,
        hidden_attributes: Sequence[str] = DEFAULT_HIDDEN,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._source = source
        self._hidden = {h.lower() for h in hidden_attributes}
        self._audit_container = dnlib.normalize(dnlib.join(AUDIT_RDN, inner.base_dn))

    # -- reads: forwarded -------------------------------------------------

    @property
    def base_dn(self) -> str:
        return self._inner.base_dn

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
        return self._inner.search(
            base, filterstr, scope, attrs, size_limit=size_limit, page_size=page_size
        )

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        return self._inner.get(dn, attrs)

    def check_password(self, dn: str, password: str) -> bool:
        return self._inner.check_password(dn, password)

    def schema_object_classes(self) -> set[str]:
        return self._inner.schema_object_classes()

    def __getattr__(self, name: str) -> Any:  # extras of concrete clients
        return getattr(self._inner, name)

    # -- writes: forwarded, then recorded -----------------------------------

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        self._inner.add(dn, attrs)
        classes = [_text(v) for v in attrs.get("objectClass", ())]
        if self._ignored(dn) or any(_bookkeeping(c) for c in classes):
            return
        lines = [
            _describe(name, values, self._hidden)
            for name, values in attrs.items()
            if name.lower() != "objectclass"
        ]
        self._record("create", dn, lines)

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        self._inner.modify(dn, changes)
        relevant = [c for c in changes if not _bookkeeping(c.attr)]
        if self._ignored(dn) or not relevant:
            return
        lines = [
            _describe(c.attr, c.values, self._hidden, c.op)
            for c in relevant
            if c.attr.lower() != "objectclass"
        ]
        self._record("modify", dn, lines)

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        entry = None if self._ignored(dn) else self._inner.get(dn, ["objectClass"])
        self._inner.delete(dn, recursive=recursive)
        if entry is None or any(_bookkeeping(c) for c in entry.texts("objectClass")):
            return
        self._record("delete", dn, ["recursive"] if recursive else [])

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        new_dn = self._inner.rename(dn, new_rdn, new_superior)
        if not self._ignored(dn):
            self._record("modify", new_dn, [f"moved from: {dn}"])
        return new_dn

    # -- helpers ------------------------------------------------------------

    def _ignored(self, dn: str) -> bool:
        """Entries of the audit log itself."""
        normalized = dnlib.normalize(dn)
        return normalized == self._audit_container or normalized.endswith(
            "," + self._audit_container
        )

    def _record(self, action: str, dn: str, lines: list[str]) -> None:
        self._sink.record(
            self._inner,
            action,
            object_type="entry",
            object_dn=dn,
            attributes=lines,
            source=self._source,
        )
