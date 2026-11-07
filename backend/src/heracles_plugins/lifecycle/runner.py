"""Lifecycle runner: apply a change to the accounts that reached their end date."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from heracles.auth.passwords import lock
from heracles.core.containers import ensure_container
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, Modification
from heracles.objects.registry import AccountLockHook
from heracles_plugins._tasks import (
    TaskReport,
    bool_of,
    date_of,
    expand_members,
    int_of,
    run_tasks,
    task_filter,
    utc,
)

TASK_CLASS = "fdTasksLifeCycle"
TASK_FILTER = task_filter(TASK_CLASS)
USER_CONTAINER_RDN = "ou=people"

type Action = Literal["none", "lock", "move", "set_attribute"]
ACTIONS: tuple[Action, ...] = ("lock", "move", "set_attribute", "none")


@dataclass(slots=True)
class LifecycleSettings:
    """Settings of the lifecycle plugin."""

    #: Attribute holding the end date: shadow style epoch days or a GeneralizedTime.
    end_date_attribute: str = "shadowExpire"
    #: Change applied to an account that reached its end date.
    action: Action = "lock"
    #: ``move``: DN of the department receiving the accounts.
    target_department: str = ""
    #: ``set_attribute``: attribute replaced by ``value``.
    attribute: str = ""
    value: str = ""


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    """An account changed by a run."""

    task_dn: str
    user_dn: str
    #: What was done: ``lock``, ``set:<attribute>``, ``move``.
    changes: tuple[str, ...]
    #: DN of the account after the run (it changes on a move).
    new_dn: str


@dataclass(slots=True)
class LifecycleReport(TaskReport):
    """What a lifecycle run did."""

    accounts: list[LifecycleRecord] = field(default_factory=lambda: [])


def _lock(directory: DirectoryClient, entry: Entry, hooks: Sequence[AccountLockHook]) -> bool:
    stored = entry.text("userPassword") or ""
    locked = lock(stored)
    changes: list[Modification] = []
    if locked != stored:
        changes.append(Modification("replace", "userPassword", [locked.encode()]))
    for hook in hooks:
        changes.extend(hook(entry, True))
    if changes:
        directory.modify(entry.dn, changes)
    return bool(changes)


def _set_attribute(directory: DirectoryClient, entry: Entry, name: str, value: str) -> bool:
    if entry.texts(name) == [value]:
        return False
    directory.modify(entry.dn, [Modification("replace", name, [value.encode()])])
    return True


def _move(directory: DirectoryClient, entry: Entry, department: str) -> str | None:
    """Move below ``ou=people`` of ``department``; ``None`` when already there."""
    superior = dnlib.join(USER_CONTAINER_RDN, department)
    parent = dnlib.parent(entry.dn)
    if parent is not None and dnlib.normalize(parent) == dnlib.normalize(superior):
        return None
    ensure_container(directory, superior)
    return directory.rename(entry.dn, dnlib.rdn(entry.dn), superior)


def _apply(
    directory: DirectoryClient,
    task: Entry,
    entry: Entry,
    settings: LifecycleSettings,
    hooks: Sequence[AccountLockHook],
) -> LifecycleRecord | None:
    done: list[str] = []
    closure = bool_of(task, "fdTasksLifeCycleEnableAccountClosure") is True
    if (settings.action == "lock" or closure) and _lock(directory, entry, hooks):
        done.append("lock")
    if (
        settings.action == "set_attribute"
        and settings.attribute
        and _set_attribute(directory, entry, settings.attribute, settings.value)
    ):
        done.append(f"set:{settings.attribute}")
    new_dn = entry.dn
    if settings.action == "move" and settings.target_department:
        moved = _move(directory, entry, settings.target_department)
        if moved is not None:
            new_dn = moved
            done.append("move")
    if not done:
        return None
    return LifecycleRecord(task.dn, entry.dn, tuple(done), new_dn)


def run_lifecycle(
    directory: DirectoryClient,
    now: datetime,
    settings: LifecycleSettings | None = None,
    *,
    lock_hooks: Sequence[AccountLockHook] = (),
) -> LifecycleReport:
    """Run every due lifecycle task once.

    A task looks at its member accounts (users, or groups and roles expanded to users) whose
    login matches ``fdTasksLifeCycleRegexPattern`` (all when empty) and whose end date plus
    the grace period ``fdTasksLifeCyclePostEndDate`` (days) is today or past, and applies
    ``settings.action``. With ``fdTasksLifeCycleEnableAccountClosure`` the account is also
    locked. Every action is idempotent, so an account already processed is not reported
    again. ``lock_hooks`` is ``registry.account_lock_hooks`` (they run on lock).
    """
    settings = settings or LifecycleSettings()
    now = utc(now)
    today = now.date()
    report = LifecycleReport()

    def process(task: Entry) -> bool:
        pattern = (task.text("fdTasksLifeCycleRegexPattern") or "").strip()
        try:
            regex = re.compile(pattern) if pattern else None
        except re.error:
            report.errors.append(f"{task.dn}: invalid login pattern")
            return False
        grace = timedelta(days=max(int_of(task, "fdTasksLifeCyclePostEndDate") or 0, 0))
        members = expand_members(
            directory,
            task.texts("fdTasksLifeCycleMembers"),
            [settings.end_date_attribute],
        )
        for member in members:
            if regex is not None and regex.search(member.text("uid") or "") is None:
                continue
            end = date_of(member, settings.end_date_attribute)
            if end is None or today < end + grace:
                continue
            entry = directory.get(member.dn)
            if entry is None:
                continue
            try:
                record = _apply(directory, task, entry, settings, lock_hooks)
            except DirectoryError as exc:
                report.errors.append(f"{entry.dn}: {type(exc).__name__}")
                continue
            if record is not None:
                report.accounts.append(record)
        return True

    run_tasks(directory, TASK_FILTER, now, process, report)
    return report
