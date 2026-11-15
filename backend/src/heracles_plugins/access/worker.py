"""What the ``access`` scheduler pass does beyond expiring grants.

* reminders: mail a person once, ``access.remind_days`` before one of their grants ends;
* auto-close: close review campaigns past their deadline (``access.auto_close``);
* orphans: cancel pending requests whose group or role no longer exists.

State lives in the application database (``ctx.database``); without one (unit tests that do
not need it) these steps are skipped.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, timedelta

import structlog

from heracles.core.access_config import AccessConfig
from heracles.core.audit import AuditSink
from heracles.core.generalized_time import format_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryError, Entry, NoSuchObjectError
from heracles.objects import ObjectService
from heracles.objects.policy import AllowAll
from heracles.objects.task_runner import TaskRunContext
from heracles_plugins.access import approvals as ap
from heracles_plugins.access import grants as g
from heracles_plugins.access import reviews as rv
from heracles_plugins.access.requests import CANCELLED, PENDING, AccessRequestStore
from heracles_plugins.access.review_routes import remover

log = structlog.get_logger(__name__)

SOURCE = "task access"
#: Keep sent-reminder rows this long past the reminder window (they only matter until the
#: grant ends).
_KEEP_REMINDERS = timedelta(days=30)
_ORPHAN_LIMIT = 5000


def reminder_key(directory_id: str, grant: g.Grant) -> str:
    """``directory|holder|kind|member|until``: one reminder per grant end date."""
    kind = grant.kind
    if grant.kind == g.ACL_KIND:
        kind = f"{kind}:{grant.acl_scope}:{dnlib.normalize(grant.acl_role)}"
    return "|".join(
        (
            directory_id,
            dnlib.normalize(grant.holder),
            kind,
            dnlib.normalize(grant.member),
            format_generalized_time(grant.until),
        )
    )


def _holder_label(entry: Entry) -> str:
    return ap.label_of(entry)


def send_reminders(
    ctx: TaskRunContext, cfg: AccessConfig, store: AccessRequestStore
) -> tuple[int, list[str]]:
    """Mail each member whose grant ends within ``remind_days``, once per end date."""
    if cfg.remind_days <= 0 or ctx.mailer is None:
        return 0, []
    now = ctx.now.astimezone(UTC)
    horizon = now + timedelta(days=cfg.remind_days)
    url = ctx.base_url.rstrip("/") + "/me"
    sent = 0
    errors: list[str] = []
    for entry in g.find_dated(ctx.directory):
        for grant in g.grants_of(entry):
            if not (now < grant.until <= horizon) or not g.holds(entry, grant):
                continue
            addresses = ap.mail_addresses(ctx.directory, [grant.member])
            if not addresses:
                continue
            key = reminder_key(ctx.directory_id, grant)
            if not store.claim_reminder(key):
                continue
            label = _holder_label(entry)
            delivered = ap.send_mail(
                ctx.mailer,
                ctx.directory,
                cfg,
                "grant_expiring",
                addresses,
                {
                    "member": grant.member,
                    "target": label,
                    "until": grant.until.date().isoformat(),
                    "url": url,
                },
            )
            if delivered:
                sent += 1
            else:
                store.release_reminder(key)  # tried again at the next pass
                errors.append(f"{entry.dn}: reminder to {grant.member} not sent")
    store.purge_reminders((now - timedelta(days=cfg.remind_days) - _KEEP_REMINDERS).timestamp())
    return sent, errors


def close_overdue_reviews(ctx: TaskRunContext) -> tuple[int, list[str]]:
    """Close the campaigns past their deadline (and resume the ones left ``closing``)."""
    now = ctx.now.timestamp()
    store = rv.ReviewStore(ctx.database, clock=lambda: now)
    sink = AuditSink(ctx.registry)
    service = ObjectService(ctx.directory, ctx.registry, policy=AllowAll())
    remove = remover(ctx.registry, service)
    closed = 0
    errors: list[str] = []
    for campaign in store.campaigns(ctx.directory_id):
        due = campaign.status == rv.CLOSING or (
            campaign.status == rv.OPEN and now > campaign.deadline
        )
        if not due:
            continue
        try:
            result = rv.close_campaign(store, campaign, ctx.directory, remove, closer="")
        except rv.CloseConflictError as exc:  # a person (or another pass) is closing it
            log.info("access_auto_close_skipped", campaign=campaign.id, reason=str(exc))
            continue
        except DirectoryError as exc:
            errors.append(f"review {campaign.name}: {type(exc).__name__}")
            continue
        if result.failed:
            errors.append(f"review {campaign.name}: {len(result.failed)} revocation(s) failed")
            continue
        closed += 1
        sink.record(
            ctx.directory,
            "access_review",
            object_type="access_review",
            object_dn=ctx.directory.base_dn,
            attributes=rv.close_audit_lines(result),
            source=SOURCE,
        )
    return closed, errors


def cancel_orphans(ctx: TaskRunContext, cfg: AccessConfig, store: AccessRequestStore) -> int:
    """Cancel pending requests whose target entry is gone (deleted or renamed)."""
    sink = AuditSink(ctx.registry)
    cancelled = 0
    for request in store.list(ctx.directory_id, status=PENDING, limit=_ORPHAN_LIMIT):
        try:
            if g.read_primary(ctx.directory, request.target_dn, ["objectClass"]) is not None:
                continue
        except NoSuchObjectError:
            pass
        except DirectoryError as exc:  # unreachable server: not proof that it is gone
            log.warning("access_orphan_check_failed", request=request.id, error=str(exc))
            continue
        done = store.decide(request, CANCELLED, by="", comment="the group or role no longer exists")
        if done is None:
            continue
        cancelled += 1
        sink.record(
            ctx.directory,
            "access_request",
            object_type="access_request",
            object_dn=done.target_dn,
            attributes=[
                f"request: {done.id}",
                f"status: {done.status}",
                f"member: {done.member_dn}",
                f"comment: {done.comment}",
            ],
            source=SOURCE,
        )
        ap.send_mail(
            ctx.mailer,
            ctx.directory,
            cfg,
            "request_decided",
            ap.mail_addresses(ctx.directory, _unique([done.requester_dn, done.member_dn])),
            {
                "target": done.target_label,
                "status": done.status,
                "decided_by": "the system",
                "comment": done.comment,
            },
        )
    return cancelled


def _unique(dns: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    for dn in dns:
        seen.setdefault(dnlib.normalize(dn), dn)
    return list(seen.values())


def new_store(ctx: TaskRunContext) -> AccessRequestStore:
    now = ctx.now.timestamp()
    return AccessRequestStore(ctx.database, clock=lambda: now)


__all__ = ["cancel_orphans", "close_overdue_reviews", "new_store", "reminder_key", "send_reminders"]
