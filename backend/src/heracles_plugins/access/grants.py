"""Time-bound grants: end dates on group/role memberships and ACL assignments.

The end date lives on the entry that holds the grant, in the multi-valued
``hrcGrantExpiry`` attribute (auxiliary class ``hrcGrantExpiries``)::

    hrcGrantExpiry: 20270101000000Z member uid=ann,ou=people,dc=example,dc=org
    hrcGrantExpiry: 20270101000000Z roleOccupant uid=bob,ou=people,dc=example,dc=org
    hrcGrantExpiry: 20270101000000Z acl:subtree:<base64 role DN> uid=ann,ou=people,...

``<time> <kind> <member DN>``: the kind names the membership attribute (``member``,
``uniqueMember``, ``roleOccupant``) or an ACL assignment (scope and role) on that entry.
:func:`expire_grants` removes the membership and the end date once the time has passed; a
date whose membership is gone (removed by hand) is dropped too.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from heracles.acl.model import AclAssignment
from heracles.acl.parser import parse_assignment, serialise_assignment
from heracles.core.generalized_time import format_generalized_time, parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)

log = structlog.get_logger(__name__)

GRANT_ATTR = "hrcGrantExpiry"
GRANT_CLASS = "hrcGrantExpiries"
ACL_ATTR = "hrcAclEntry"
#: Membership attributes whose values may carry an end date.
MEMBER_ATTRS = ("member", "uniqueMember", "roleOccupant")
ACL_KIND = "acl"


class GrantError(ValueError):
    """The grant does not exist, or the request is malformed."""


def _b64e(text: str) -> str:
    return base64.b64encode(text.encode()).decode("ascii")


def _b64d(text: str) -> str:
    try:
        return base64.b64decode(text.encode("ascii"), validate=True).decode()
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError(text) from exc


def _canonical_kind(kind: str) -> str | None:
    for attr in MEMBER_ATTRS:
        if kind.lower() == attr.lower():
            return attr
    return None


@dataclass(frozen=True, slots=True)
class Grant:
    """One end date: who (``member``) loses what (``kind``) on ``holder`` at ``until``."""

    holder: str
    kind: str  # a MEMBER_ATTRS name, or "acl"
    member: str
    until: datetime
    acl_scope: str = ""
    acl_role: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        """What the date applies to (one date per key)."""
        return (
            self.kind.lower(),
            self.acl_scope,
            dnlib.normalize(self.acl_role) if self.acl_role else "",
            dnlib.normalize(self.member),
        )

    def value(self) -> str:
        stamp = format_generalized_time(self.until)
        kind = (
            self.kind if self.kind != ACL_KIND else f"acl:{self.acl_scope}:{_b64e(self.acl_role)}"
        )
        return f"{stamp} {kind} {self.member}"

    def to_json(self) -> dict[str, str]:
        out = {
            "holder": self.holder,
            "kind": self.kind,
            "member": self.member,
            "until": self.until.isoformat(),
        }
        if self.kind == ACL_KIND:
            out["acl_scope"] = self.acl_scope
            out["acl_role"] = self.acl_role
        return out


def parse_grant(holder: str, raw: str) -> Grant | None:
    """``None`` for a value that cannot be read (logged; never expired blindly)."""
    stamp, _, rest = raw.strip().partition(" ")
    kind_text, _, member = rest.partition(" ")
    member = member.strip()
    try:
        until = parse_generalized_time(stamp)
    except ValueError:
        log.warning("grant_value_ignored", holder=holder, value=raw)
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if not member or "=" not in member:
        log.warning("grant_value_ignored", holder=holder, value=raw)
        return None
    if kind_text.startswith("acl:"):
        _, _, tail = kind_text.partition(":")
        scope, _, role_b64 = tail.partition(":")
        try:
            role = _b64d(role_b64)
        except ValueError:
            log.warning("grant_value_ignored", holder=holder, value=raw)
            return None
        return Grant(holder, ACL_KIND, member, until, acl_scope=scope, acl_role=role)
    kind = _canonical_kind(kind_text)
    if kind is None:
        log.warning("grant_value_ignored", holder=holder, value=raw)
        return None
    return Grant(holder, kind, member, until)


def grants_of(entry: Entry) -> list[Grant]:
    out: list[Grant] = []
    for raw in entry.texts(GRANT_ATTR):
        grant = parse_grant(entry.dn, raw)
        if grant is not None:
            out.append(grant)
    return out


# -- is the grant there? --------------------------------------------------------------------


def _member_value(entry: Entry, attr: str, member: str) -> bytes | None:
    """The stored value of ``attr`` naming ``member`` (DNs compared normalised)."""
    wanted = dnlib.normalize(member)
    for value in entry.get(attr):
        try:
            if dnlib.normalize(value.decode()) == wanted:
                return value
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def _assignments(entry: Entry) -> list[tuple[bytes, AclAssignment]]:
    out: list[tuple[bytes, AclAssignment]] = []
    for raw in entry.get(ACL_ATTR):
        parsed = parse_assignment(raw.decode("utf-8", "replace"))
        if isinstance(parsed, AclAssignment):
            out.append((raw, parsed))
    return out


def _acl_matches(assignment: AclAssignment, grant: Grant) -> bool:
    return assignment.scope.value == grant.acl_scope and dnlib.normalize(
        assignment.role_dn
    ) == dnlib.normalize(grant.acl_role)


def holds(entry: Entry, grant: Grant) -> bool:
    """Whether ``entry`` currently grants what ``grant`` dates."""
    if grant.kind == ACL_KIND:
        wanted = dnlib.normalize(grant.member)
        return any(
            _acl_matches(a, grant)
            and any(dnlib.normalize(m) == wanted for m in a.members if m != "*")
            for _raw, a in _assignments(entry)
        )
    return _member_value(entry, grant.kind, grant.member) is not None


# -- setting and clearing ---------------------------------------------------------------------


def set_end_date(
    directory: DirectoryClient,
    holder: str,
    kind: str,
    member: str,
    until: datetime | None,
    *,
    acl_scope: str = "",
    acl_role: str = "",
) -> Grant | None:
    """Give a grant an end date (``until``), or make it permanent (``None``).

    Raises :class:`GrantError` when the grant does not exist on ``holder``.
    """
    canonical = ACL_KIND if kind == ACL_KIND else _canonical_kind(kind)
    if canonical is None:
        raise GrantError(f"unknown kind {kind!r}")
    if canonical == ACL_KIND and not (acl_scope and acl_role):
        raise GrantError("an ACL grant needs its scope and role")
    entry = directory.get(
        holder, ["objectClass", GRANT_ATTR, canonical if canonical != ACL_KIND else ACL_ATTR]
    )
    if entry is None:
        raise GrantError("no such entry")
    moment = (until or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    grant = Grant(entry.dn, canonical, member, moment, acl_scope=acl_scope, acl_role=acl_role)
    if not holds(entry, grant):
        raise GrantError("no such grant")
    stale = [
        raw.encode()
        for raw in entry.texts(GRANT_ATTR)
        if (g := parse_grant(entry.dn, raw)) is not None and g.key == grant.key
    ]
    changes: list[Modification] = []
    if stale:
        changes.append(Modification("delete", GRANT_ATTR, stale))
    if until is not None:
        if not entry.has_object_class(GRANT_CLASS):
            changes.append(Modification("add", "objectClass", [GRANT_CLASS.encode()]))
        changes.append(Modification("add", GRANT_ATTR, [grant.value().encode()]))
    if changes:
        directory.modify(entry.dn, changes)
    return grant if until is not None else None


def end_dates_for_removed(entry: Entry, removed: Iterable[tuple[str, str]]) -> list[bytes]:
    """The stored end dates of memberships that were removed (``(attr, member DN)`` pairs)."""
    gone = {(a.lower(), dnlib.normalize(m)) for a, m in removed}
    out: list[bytes] = []
    for raw in entry.texts(GRANT_ATTR):
        grant = parse_grant(entry.dn, raw)
        if (
            grant is not None
            and grant.kind != ACL_KIND
            and (
                grant.kind.lower(),
                dnlib.normalize(grant.member),
            )
            in gone
        ):
            out.append(raw.encode())
    return out


# -- expiry ----------------------------------------------------------------------------------


@dataclass(slots=True)
class ExpiryReport:
    expired: int = 0
    dropped: int = 0  # end dates whose grant was already gone
    errors: list[str] = field(default_factory=lambda: [])
    expired_grants: list[Grant] = field(default_factory=lambda: [])


def _revoke_changes(entry: Entry, grant: Grant) -> list[Modification]:
    if grant.kind != ACL_KIND:
        value = _member_value(entry, grant.kind, grant.member)
        return [Modification("delete", grant.kind, [value])] if value is not None else []
    wanted = dnlib.normalize(grant.member)
    changes: list[Modification] = []
    for raw, assignment in _assignments(entry):
        if not _acl_matches(assignment, grant):
            continue
        kept = tuple(m for m in assignment.members if m == "*" or dnlib.normalize(m) != wanted)
        if kept == assignment.members:
            continue
        changes.append(Modification("delete", ACL_ATTR, [raw]))
        if kept:
            rebuilt = AclAssignment(
                index=assignment.index,
                scope=assignment.scope,
                role_dn=assignment.role_dn,
                members=kept,
                user_filter=assignment.user_filter,
                target_filter=assignment.target_filter,
            )
            changes.append(Modification("add", ACL_ATTR, [serialise_assignment(rebuilt).encode()]))
    return changes


def _attrs_needed() -> list[str]:
    return ["objectClass", GRANT_ATTR, ACL_ATTR, *MEMBER_ATTRS]


def find_dated(directory: DirectoryClient, base: str | None = None) -> list[Entry]:
    try:
        return list(
            directory.search(
                base or directory.base_dn, f"({GRANT_ATTR}=*)", Scope.SUBTREE, _attrs_needed()
            )
        )
    except NoSuchObjectError:
        return []


def expire_grants(directory: DirectoryClient, now: datetime) -> ExpiryReport:
    """Remove every grant whose end date has passed (and dates left without a grant)."""
    report = ExpiryReport()
    now = now.astimezone(UTC)
    for entry in find_dated(directory):
        changes: list[Modification] = []
        old_dates: list[bytes] = []
        for raw in entry.texts(GRANT_ATTR):
            grant = parse_grant(entry.dn, raw)
            if grant is None:
                continue
            if not holds(entry, grant):
                old_dates.append(raw.encode())
                report.dropped += 1
                continue
            if grant.until > now:
                continue
            revoke = _revoke_changes(entry, grant)
            if not revoke:
                continue
            changes.extend(revoke)
            old_dates.append(raw.encode())
            report.expired += 1
            report.expired_grants.append(grant)
        if not changes and not old_dates:
            continue
        if old_dates:
            changes.append(Modification("delete", GRANT_ATTR, old_dates))
        try:
            directory.modify(entry.dn, _merge(changes))
        except DirectoryError as exc:
            report.errors.append(f"{entry.dn}: {type(exc).__name__}")
            log.warning("grant_expiry_failed", dn=entry.dn, error=str(exc))
    return report


def _merge(changes: Sequence[Modification]) -> list[Modification]:
    """Deletes first, one per attribute (a server refuses deleting a value twice), then adds."""
    deletes: dict[str, list[bytes]] = {}
    others: list[Modification] = []
    for change in changes:
        if change.op == "delete" and change.values:
            bucket = deletes.setdefault(change.attr, [])
            bucket.extend(v for v in change.values if v not in bucket)
        else:
            others.append(change)
    return [Modification("delete", attr, values) for attr, values in deletes.items()] + others


def dated_memberships(directory: DirectoryClient, member: str) -> list[Grant]:
    """End dates of the grants one person holds."""
    wanted = dnlib.normalize(member)
    out: list[Grant] = []
    for entry in find_dated(directory):
        for grant in grants_of(entry):
            if dnlib.normalize(grant.member) == wanted and holds(entry, grant):
                out.append(grant)
    return out


__all__ = [
    "ACL_KIND",
    "GRANT_ATTR",
    "GRANT_CLASS",
    "MEMBER_ATTRS",
    "ExpiryReport",
    "Grant",
    "GrantError",
    "dated_memberships",
    "end_dates_for_removed",
    "expire_grants",
    "grants_of",
    "holds",
    "parse_grant",
    "set_end_date",
]
