"""Runner skeleton shared by the task plugins.

A run examines every task of one kind, processes the due ones and reschedules
them (or deactivates them) so a second call right after does nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from heracles.core.generalized_time import format_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles_plugins._tasks.helpers import (
    STATUS_ACTIVATED,
    STATUS_DEACTIVATED,
    bool_of,
    next_execution,
    time_of,
    utc,
)

log = structlog.get_logger(__name__)

TASKS_RDN = "ou=tasks"


def task_filter(object_class: str) -> str:
    """LDAP filter of the tasks of one kind."""
    return f"(&(objectClass=hrcTasks)(objectClass={object_class}))"


@dataclass(slots=True)
class TaskReport:
    """Counters common to every task kind."""

    tasks_examined: int = 0
    tasks_run: int = 0
    errors: list[str] = field(default_factory=lambda: [])


def find_tasks(directory: DirectoryClient, flt: str) -> list[Entry]:
    """Tasks matching ``flt`` below the root ``ou=tasks`` container."""
    try:
        return list(directory.search(dnlib.join(TASKS_RDN, directory.base_dn), flt))
    except NoSuchObjectError:
        return []


def is_due(task: Entry, now: datetime) -> bool:
    """Activated and past its next execution date (or never scheduled)."""
    status = (task.text("hrcTasksStatus") or "").strip().lower()
    if status != STATUS_ACTIVATED.lower():
        return False
    next_exec = time_of(task, "hrcTasksNextExec")
    return next_exec is None or next_exec <= now


def reschedule(directory: DirectoryClient, task: Entry, now: datetime) -> str | None:
    """Update last/next execution; returns an error message for a bad schedule."""
    repeatable = bool_of(task, "hrcTasksRepeatable") is True
    changes = [
        Modification("replace", "hrcTasksLastExec", [format_generalized_time(now).encode()]),
    ]
    error: str | None = None
    following = next_execution(now, task.text("hrcTasksRepeatableSchedule")) if repeatable else None
    if repeatable and following is None:
        error = f"{task.dn}: unknown repeat schedule, task deactivated"
    if following is not None:
        changes.append(
            Modification(
                "replace", "hrcTasksNextExec", [format_generalized_time(following).encode()]
            )
        )
    else:
        if task.get("hrcTasksNextExec"):
            changes.append(Modification("delete", "hrcTasksNextExec"))
        changes.append(Modification("replace", "hrcTasksStatus", [STATUS_DEACTIVATED.encode()]))
    directory.modify(task.dn, changes)
    return error


def run_tasks(
    directory: DirectoryClient,
    flt: str,
    now: datetime,
    process: Callable[[Entry], bool],
    report: TaskReport,
    *,
    accept: Callable[[Entry], bool] | None = None,
) -> None:
    """Process every due task matching ``flt``.

    ``process(task)`` returns ``False`` when the task could not run (it is then left as
    it is, to be retried); directory errors are collected in ``report.errors``.
    """
    now = utc(now)
    for task in find_tasks(directory, flt):
        report.tasks_examined += 1
        if not is_due(task, now) or (accept is not None and not accept(task)):
            continue
        try:
            if not process(task):
                continue
            error = reschedule(directory, task, now)
        except DirectoryError as exc:
            report.errors.append(f"{task.dn}: {type(exc).__name__}")
            log.warning("task_failed", task=task.dn, error=type(exc).__name__)
            continue
        if error:
            report.errors.append(error)
        report.tasks_run += 1


def purge_older_than(
    directory: DirectoryClient,
    container: str,
    object_class: str,
    attr: str,
    cutoff: datetime,
    errors: list[str],
) -> int:
    """Delete the entries of ``container`` whose GeneralizedTime ``attr`` is before ``cutoff``."""
    flt = f"(&(objectClass={object_class})({attr}<={format_generalized_time(cutoff)}))"
    try:
        found = list(directory.search(container, flt, Scope.ONE, ["objectClass", attr]))
    except NoSuchObjectError:
        return 0
    purged = 0
    for entry in found:
        stamp = time_of(entry, attr)
        if stamp is None or stamp >= cutoff:
            continue
        try:
            directory.delete(entry.dn)
        except NoSuchObjectError:
            continue
        except DirectoryError as exc:
            errors.append(f"{entry.dn}: {type(exc).__name__}")
            continue
        purged += 1
    return purged
