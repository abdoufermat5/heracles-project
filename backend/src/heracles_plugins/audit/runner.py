"""Audit task runner: purge old events and optionally forward new ones to syslog."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from heracles.core.generalized_time import format_generalized_time
from heracles.ldap.client import DirectoryClient, Entry, NoSuchObjectError, Scope
from heracles_plugins._tasks import (
    TaskReport,
    bool_of,
    int_of,
    purge_older_than,
    run_tasks,
    task_filter,
    time_of,
    utc,
)
from heracles_plugins.audit.events import (
    EVENT_CLASS,
    AuditSettings,
    audit_container,
    format_event,
)

TASK_CLASS = "hrcAuditTasks"
TASK_FILTER = task_filter(TASK_CLASS)
#: Standard library logger receiving the forwarded events; bind a syslog handler to it.
SYSLOG_LOGGER = "heracles.audit"


@dataclass(slots=True)
class AuditReport(TaskReport):
    """What an audit run did."""

    events_purged: int = 0
    events_forwarded: int = 0


def _forward(directory: DirectoryClient, task: Entry, since: datetime, report: AuditReport) -> None:
    prefix = task.text("hrcAuditSyslogPrefix") or ""
    logger = logging.getLogger(SYSLOG_LOGGER)
    flt = f"(&(objectClass={EVENT_CLASS})(hrcAuditDateTime>={format_generalized_time(since)}))"
    try:
        events = list(directory.search(audit_container(directory), flt, Scope.ONE))
    except NoSuchObjectError:
        return
    events.sort(key=lambda e: (e.text("hrcAuditDateTime") or "", e.dn))
    for event in events:
        stamp = time_of(event, "hrcAuditDateTime")
        if stamp is None or stamp <= since:
            continue
        logger.info("%s%s", prefix, format_event(event))
        report.events_forwarded += 1


def run_audit(
    directory: DirectoryClient,
    now: datetime,
    settings: AuditSettings | None = None,
) -> AuditReport:
    """Run every due audit task once.

    A task purges the events older than its retention (``hrcAuditTasksRetention`` days, or
    ``settings.retention_days``; 0 keeps everything) and, when syslog forwarding is enabled,
    logs the events recorded since its previous execution to the ``heracles.audit`` logger.
    """
    settings = settings or AuditSettings()
    now = utc(now)
    report = AuditReport()

    def process(task: Entry) -> bool:
        if bool_of(task, "hrcAuditSyslogEnabled") is True:
            since = (
                time_of(task, "hrcTasksLastExec") or time_of(task, "hrcTasksCreationDate") or now
            )
            _forward(directory, task, since, report)
        days = int_of(task, "hrcAuditTasksRetention")
        days = settings.retention_days if days is None else days
        if days > 0:
            report.events_purged += purge_older_than(
                directory,
                audit_container(directory),
                EVENT_CLASS,
                "hrcAuditDateTime",
                now - timedelta(days=days),
                report.errors,
            )
        return True

    run_tasks(directory, TASK_FILTER, now, process, report)
    return report
