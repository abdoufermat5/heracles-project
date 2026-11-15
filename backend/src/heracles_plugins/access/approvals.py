"""What may be requested, who approves it, and applying an approved request.

* Requestable: groups (``groupOfNames``, membership ``member``) and roles
  (``organizationalRole``, ``roleOccupant``) matching ``access.requestable`` (default
  ``(owner=*)``: entries with an owner).
* Approvers of a request: the entry's ``owner`` values (a user, or the members of a group or
  role named as owner), the members of the ``access.approvers`` groups, and administrators.
  Nobody approves their own request (administrators excepted).
* Applying: the membership is added through the object service of the entry's type, with the
  approver as author (hooks, triggers and audit as for any edit), then dated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

import structlog

from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain
from heracles.auth.mail import Mailer
from heracles.core.access_config import AccessConfig
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, NoSuchObjectError, Scope
from heracles.ldap.filter import escape_filter_value
from heracles.objects import ObjectService
from heracles.objects.policy import AllowAll
from heracles_plugins._tasks.helpers import render_template
from heracles_plugins.access import grants as g
from heracles_plugins.access.requests import AccessRequest
from heracles_plugins.access.rights import holder_types

log = structlog.get_logger(__name__)

#: Structural class -> membership attribute of the entries that can be requested.
KINDS: Mapping[str, str] = {"groupofnames": "member", "organizationalrole": "roleOccupant"}
_ATTRS = ["objectClass", "cn", "description", "owner", "member", "roleOccupant"]


def kind_of(entry: Entry) -> str | None:
    for oc in entry.texts("objectClass"):
        kind = KINDS.get(oc.lower())
        if kind:
            return kind
    return None


def _filter(cfg: AccessConfig) -> str:
    extra = cfg.requestable.strip()
    if extra and not extra.startswith("("):
        extra = f"({extra})"
    return f"(&(|(objectClass=groupOfNames)(objectClass=organizationalRole)){extra})"


def requestable(directory: DirectoryClient, cfg: AccessConfig) -> list[Entry]:
    try:
        return list(directory.search(directory.base_dn, _filter(cfg), Scope.SUBTREE, _ATTRS))
    except NoSuchObjectError:
        return []


def requestable_entry(directory: DirectoryClient, cfg: AccessConfig, dn: str) -> Entry | None:
    try:
        return next(iter(directory.search(dn, _filter(cfg), Scope.BASE, _ATTRS)), None)
    except (NoSuchObjectError, DirectoryError):
        return None


def label_of(entry: Entry) -> str:
    return entry.text("cn") or dnlib.rdn(entry.dn).partition("=")[2]


def holds_membership(entry: Entry, member: str) -> bool:
    kind = kind_of(entry)
    wanted = dnlib.normalize(member)
    return kind is not None and any(dnlib.normalize(v) == wanted for v in entry.texts(kind))


def _expand(directory: DirectoryClient, dns: Iterable[str]) -> set[str]:
    """Normalised user DNs: a group or role stands for its members (one level)."""
    out: set[str] = set()
    for dn in dns:
        try:
            entry = directory.get(dn, ["objectClass", "member", "roleOccupant", "uniqueMember"])
        except DirectoryError:
            entry = None
        kind = kind_of(entry) if entry is not None else None
        if entry is None or kind is None:
            out.add(dnlib.normalize(dn))
            continue
        for attr in ("member", "uniqueMember", "roleOccupant"):
            out.update(dnlib.normalize(v) for v in entry.texts(attr))
    return out


def approvers_of(directory: DirectoryClient, cfg: AccessConfig, target: Entry) -> set[str]:
    return _expand(directory, [*target.texts("owner"), *cfg.approvers])


def can_approve(
    user: CurrentUser, domain: Domain, cfg: AccessConfig, target: Entry, request: AccessRequest
) -> bool:
    if domain.is_admin(user.dn):
        return True
    if dnlib.normalize(user.dn) in {
        dnlib.normalize(request.requester_dn),
        dnlib.normalize(request.member_dn),
    }:
        return False
    return dnlib.normalize(user.dn) in approvers_of(user.directory, cfg, target)


class ApplyError(Exception):
    """The approved request cannot be applied (the reason is shown to the approver)."""


def current_end_date(entry: Entry, kind: str, member: str) -> datetime | None:
    wanted = dnlib.normalize(member)
    for grant in g.grants_of(entry):
        if grant.kind == kind and dnlib.normalize(grant.member) == wanted:
            return grant.until
    return None


def apply(user: CurrentUser, domain: Domain, request: AccessRequest, now: datetime) -> None:
    """Add (or extend) the membership with the approver as author, then date it.

    Everything is read from a write server. When dating fails after the membership was
    added, the addition is undone, so an approval never leaves access broader than asked.
    """
    directory = user.directory
    entry = g.read_primary(directory, request.target_dn)
    if entry is None:
        raise ApplyError("the requested group or role no longer exists")
    if g.read_primary(directory, request.member_dn, ["objectClass"]) is None:
        raise ApplyError("the person no longer exists")
    until = datetime.fromisoformat(request.until) if request.until else None
    if until is not None and until <= now:
        raise ApplyError("the requested end date has passed")
    kind = request.target_kind
    found = holder_types(domain, entry, kind)
    if not found:
        raise ApplyError(f"no type edits {kind} on this entry")
    info, tab = found[0]
    current = entry.texts(kind)
    present = any(dnlib.normalize(v) == dnlib.normalize(request.member_dn) for v in current)
    service = ObjectService(
        directory, domain.registry, policy=AllowAll(), events=domain.events(user)
    )
    if not present:
        service.update(
            info.name, entry.dn, {tab: {"values": {kind: [*current, request.member_dn]}}}
        )
    try:
        if until is not None or current_end_date(entry, kind, request.member_dn) is not None:
            g.set_end_date(directory, entry.dn, kind, request.member_dn, until)
    except Exception:
        if not present:
            try:
                service.update(info.name, entry.dn, {tab: {"values": {kind: current}}})
            except Exception as exc:  # pragma: no cover - reported in the log
                log.error("access_apply_rollback_failed", dn=entry.dn, error=str(exc))
        raise


# -- mail --------------------------------------------------------------------------------------

DEFAULT_MAILS: Mapping[str, tuple[str, str]] = {
    "request_submitted": (
        "Access request: {target}",
        "{requester} asks for {member} to join {target}.\n\nReason: {reason}\n"
        "End date: {until}\n\nReview it in the console: {url}\n",
    ),
    "request_decided": (
        "Your access request for {target} was {status}",
        "Your request to join {target} was {status} by {decided_by}.\n\n{comment}\n",
    ),
    "review_assigned": (
        "Access review: {campaign}",
        "You are asked to review {count} access grants in “{campaign}” before {deadline}."
        "\n\nOpen the console: {url}\n",
    ),
}


def mail_addresses(directory: DirectoryClient, dns: Iterable[str]) -> list[str]:
    out: list[str] = []
    for dn in dns:
        try:
            entry = directory.get(dn, ["mail"])
        except DirectoryError:
            continue
        address = entry.text("mail") if entry is not None else None
        if address and address not in out:
            out.append(address)
    return out


def _template(directory: DirectoryClient, name: str) -> tuple[str, str] | None:
    if not name:
        return None
    flt = f"(&(objectClass=hrcMailTemplate)(cn={escape_filter_value(name)}))"
    try:
        entry = next(
            iter(
                directory.search(
                    directory.base_dn,
                    flt,
                    Scope.SUBTREE,
                    ["hrcMailTemplateSubject", "hrcMailTemplateBody"],
                )
            ),
            None,
        )
    except DirectoryError:
        return None
    if entry is None:
        return None
    return entry.text("hrcMailTemplateSubject") or "", entry.text("hrcMailTemplateBody") or ""


def send_mail(
    mailer: Mailer | None,
    directory: DirectoryClient,
    cfg: AccessConfig,
    kind: str,
    recipients: Sequence[str],
    values: Mapping[str, str],
) -> int:
    """Mail ``recipients`` (addresses) with the configured template or the built-in wording."""
    if mailer is None or not recipients:
        return 0
    template = _template(directory, getattr(cfg.mail, kind, "")) or DEFAULT_MAILS[kind]
    subject = render_template(template[0], dict(values))
    body = render_template(template[1], dict(values))
    sent = 0
    for address in recipients:
        try:
            mailer.send(address, subject, body)
            sent += 1
        except Exception as exc:  # a mail failure never fails the request
            log.warning("access_mail_failed", kind=kind, error=type(exc).__name__)
    return sent


__all__ = [
    "KINDS",
    "ApplyError",
    "apply",
    "approvers_of",
    "can_approve",
    "current_end_date",
    "holds_membership",
    "kind_of",
    "label_of",
    "mail_addresses",
    "requestable",
    "requestable_entry",
    "send_mail",
]
