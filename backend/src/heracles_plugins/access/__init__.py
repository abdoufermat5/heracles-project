"""Access governance: time-bound grants, access requests and access reviews.

* Grants: end dates on group/role memberships and ACL assignments (``hrcGrantExpiry``, see
  :mod:`heracles_plugins.access.grants`); the ``access`` task runner removes expired grants at
  every scheduler pass (written through the auditing directory, so each removal is audited).
* Requests and reviews keep their state in the application database. The same pass mails
  reminders ahead of end dates, closes review campaigns past their deadline and cancels
  requests whose group or role is gone (:mod:`heracles_plugins.access.worker`).
* ``/api/v2/access``: the routes.

Configuration: the top-level ``access`` section (:mod:`heracles.core.access_config`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog

from heracles.core.access_config import access_config
from heracles.ldap.client import DirectoryClient, DirectoryError, Modification
from heracles.objects import Plugin
from heracles.objects.policy import EventContext, NullEvents
from heracles.objects.registry import EventsContext
from heracles.objects.task_runner import TaskRunContext, TaskRunner
from heracles_plugins._tasks import TaskReport
from heracles_plugins.access import grants as g
from heracles_plugins.access import worker as w
from heracles_plugins.access.router import build_router

log = structlog.get_logger(__name__)

PLUGIN_NAME = "access"


@dataclass(slots=True)
class AccessReport(TaskReport):
    """What an access pass did."""

    grants_expired: int = 0
    end_dates_dropped: int = 0
    #: Due but kept: the last member of a group (which must have one).
    grants_overdue: int = 0
    #: Mails sent ahead of an end date (``access.remind_days``).
    reminders_sent: int = 0
    #: Review campaigns closed at their deadline (``access.auto_close``).
    reviews_closed: int = 0
    #: Pending requests cancelled because their group or role is gone.
    requests_orphaned: int = 0


def _run(ctx: TaskRunContext) -> AccessReport:
    report = AccessReport()
    result = g.expire_grants(ctx.directory, ctx.now)
    report.grants_expired = result.expired
    report.end_dates_dropped = result.dropped
    report.grants_overdue = result.overdue
    report.errors.extend(result.errors)
    if ctx.database is None:  # no application database: nothing to keep state in
        return report
    cfg = access_config()
    requests = w.new_store(ctx)
    # each step is isolated: one failing does not stop the others
    reminders = _guarded(report, lambda: w.send_reminders(ctx, cfg, requests))
    report.reminders_sent = reminders[0] if reminders else 0
    if cfg.auto_close:
        closed = _guarded(report, lambda: w.close_overdue_reviews(ctx))
        report.reviews_closed = closed[0] if closed else 0
    orphans = _guarded(report, lambda: (w.cancel_orphans(ctx, cfg, requests), []))
    report.requests_orphaned = orphans[0] if orphans else 0
    return report


def _guarded(
    report: AccessReport, step: Callable[[], tuple[int, list[str]]]
) -> tuple[int, list[str]] | None:
    """Run one step: its errors go to the report (a failure does not stop the pass)."""
    try:
        outcome = step()
    except Exception as exc:
        log.warning("access_step_failed", error=str(exc), kind=type(exc).__name__)
        report.errors.append(f"{type(exc).__name__}: {exc}")
        return None
    report.errors.extend(outcome[1])
    return outcome


def _removed_members(ctx: EventContext) -> list[tuple[str, str]]:
    """``(attribute, member DN)`` pairs a modification took away."""
    before: dict[str, list[bytes]] = ctx.before.raw if ctx.before is not None else {}
    out: list[tuple[str, str]] = []
    for attr in g.MEMBER_ATTRS:
        old: list[bytes] = []
        for key, values in before.items():
            if key.lower() == attr.lower():
                old = list(values)
        current: set[bytes] = {bytes(v) for v in old}
        touched = False
        for change in ctx.changes:
            if change.attr.lower() != attr.lower():
                continue
            touched = True
            if change.op == "replace":
                current = {bytes(v) for v in change.values}
            elif change.op == "delete":
                current = (
                    set() if not change.values else current - {bytes(v) for v in change.values}
                )
            else:
                current |= {bytes(v) for v in change.values}
        if not touched:
            continue
        kept = {v.decode("utf-8", "replace").lower() for v in current}
        out.extend(
            (attr, v.decode("utf-8", "replace"))
            for v in old
            if v.decode("utf-8", "replace").lower() not in kept
        )
    return out


class AccessEvents(NullEvents):
    """Drop the end date of a membership removed by hand (a later re-add starts permanent)."""

    def __init__(self, directory: DirectoryClient) -> None:
        self._directory = directory

    def post_modify(self, ctx: EventContext) -> None:
        removed = _removed_members(ctx)
        if not removed:
            return
        try:
            entry = self._directory.get(ctx.dn, ["objectClass", g.GRANT_ATTR])
            if entry is None:
                return
            stale = g.end_dates_for_removed(entry, removed)
            if stale:
                self._directory.modify(entry.dn, [Modification("delete", g.GRANT_ATTR, stale)])
        except DirectoryError as exc:  # the runner drops orphaned dates later anyway
            log.warning("grant_end_date_cleanup_failed", dn=ctx.dn, error=type(exc).__name__)


def _events(ctx: EventsContext) -> AccessEvents:
    return AccessEvents(ctx.directory)


def plugin() -> Plugin:
    """Entry point of the access plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(),
        required_object_classes=(g.GRANT_CLASS,),
        object_events=(_events,),
        task_runners=(TaskRunner(PLUGIN_NAME, _run),),
        api_routers=(build_router,),
    )


__all__ = ["AccessEvents", "AccessReport", "plugin"]
