"""Audit events: writing them as entries below ``ou=audit`` and reading them back."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog

from heracles.core.audit import (
    ACTIONS,
    EVENT_CLASS,
    audit_container,
    write_event,
)
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles.objects.policy import EventContext, NullEvents

log = structlog.get_logger(__name__)

#: Attribute values longer than this are cut in the log.
MAX_VALUE_LENGTH = 256


@dataclass(slots=True)
class AuditSettings:
    """Settings of the audit plugin."""

    #: Events older than this are purged by the audit task (a task may override it).
    retention_days: int = 365
    #: Audited actions.
    actions: tuple[str, ...] = ACTIONS
    #: Attributes whose values are never written to the log (only their names).
    hidden_attributes: tuple[str, ...] = ("userPassword",)
    #: Object types that are not audited (the log itself and its helpers).
    ignored_types: tuple[str, ...] = ("audit_event",)


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return "<binary>"


def _cut(text: str) -> str:
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 3] + "..."


def describe_values(
    name: str, values: Sequence[bytes], hidden: Sequence[str], *, op: str | None = None
) -> str:
    """``attr: v1, v2`` (``attr: ***`` for hidden attributes)."""
    prefix = f"{op} " if op else ""
    if name.lower() in {h.lower() for h in hidden}:
        return f"{prefix}{name}: ***"
    if not values:
        return f"{prefix}{name}: (removed)"
    return _cut(f"{prefix}{name}: " + ", ".join(_text(v) for v in values))


def _created_attributes(ctx: EventContext, hidden: Sequence[str]) -> list[str]:
    if ctx.after is None:
        return []
    return [
        describe_values(name, values, hidden)
        for name, values in ctx.after.raw.items()
        if name.lower() != "objectclass"
    ]


def _changed_attributes(changes: Sequence[Modification], hidden: Sequence[str]) -> list[str]:
    return [
        describe_values(c.attr, c.values, hidden, op=c.op)
        for c in changes
        if c.attr.lower() != "objectclass"
    ]


@dataclass(slots=True)
class AuditEvents(NullEvents):
    """``ObjectEvents`` implementation recording create, modify and delete operations.

    One instance serves one request: it knows the acting user and client address.
    Failures to write an event are logged and never break the audited operation.

    Wiring (not done by the framework): when building the ``ObjectService`` of a request
    (``Domain.service``) pass ``events=AuditEvents(user.directory, author_dn=user.dn,
    author_ip=<client address>, settings=registry.settings["audit"])``. To combine it with
    other hooks, write a small ``ObjectEvents`` that calls each of them in turn.
    """

    directory: DirectoryClient
    author_dn: str
    author_ip: str = ""
    settings: AuditSettings = field(default_factory=AuditSettings)

    def _record(self, action: str, ctx: EventContext, attributes: Sequence[str]) -> None:
        if action not in self.settings.actions or ctx.type_name in self.settings.ignored_types:
            return
        try:
            write_event(
                self.directory,
                action=action,
                object_type=ctx.type_name,
                object_dn=ctx.dn,
                author_dn=self.author_dn,
                author_ip=self.author_ip,
                attributes=attributes,
            )
        except DirectoryError as exc:
            log.warning("audit_event_failed", object=ctx.dn, error=type(exc).__name__)

    def post_create(self, ctx: EventContext) -> None:
        self._record("create", ctx, _created_attributes(ctx, self.settings.hidden_attributes))

    def post_modify(self, ctx: EventContext) -> None:
        self._record(
            "modify", ctx, _changed_attributes(ctx.changes, self.settings.hidden_attributes)
        )

    def post_delete(self, ctx: EventContext) -> None:
        self._record("delete", ctx, [])

    def post_lock(self, ctx: EventContext) -> None:
        self._record(
            "modify", ctx, _changed_attributes(ctx.changes, self.settings.hidden_attributes)
        )

    def post_unlock(self, ctx: EventContext) -> None:
        self.post_lock(ctx)

    def post_second_factor_reset(self, ctx: EventContext) -> None:
        self._record(
            "second_factor", ctx, _changed_attributes(ctx.changes, self.settings.hidden_attributes)
        )


def format_event(entry: Entry) -> str:
    """One line summary of an event entry."""
    stamp = entry.text("hrcAuditDateTime") or ""
    parts = [
        stamp,
        entry.text("hrcAuditAction") or "",
        entry.text("hrcAuditObjectType") or "",
        entry.text("hrcAuditObject") or "",
        f"by {entry.text('hrcAuditAuthorDN') or '?'}",
        entry.text("hrcAuditResult") or "",
    ]
    return " ".join(p for p in parts if p)


def events_for(directory: DirectoryClient, dn: str, limit: int = 50) -> list[Entry]:
    """Latest events about ``dn`` or made by it, newest first."""
    quoted = escape_filter_value(dn)
    flt = f"(&(objectClass={EVENT_CLASS})(|(hrcAuditObject={quoted})(hrcAuditAuthorDN={quoted})))"
    try:
        found = [
            e
            for e in directory.search(audit_container(directory), flt, Scope.ONE)
            if dnlib.normalize(e.text("hrcAuditObject") or "") == dnlib.normalize(dn)
            or dnlib.normalize(e.text("hrcAuditAuthorDN") or "") == dnlib.normalize(dn)
        ]
    except NoSuchObjectError:
        return []
    found.sort(key=lambda e: (e.text("hrcAuditDateTime") or "", e.dn), reverse=True)
    return found[:limit]
