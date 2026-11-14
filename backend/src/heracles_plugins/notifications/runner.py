"""Notifications runner: mail when monitored attributes of members change.

Each task keeps a snapshot of the monitored values of every member, one child entry per
member below the task (``cn=<hash>``, objectClass ``hrcTasks``, JSON in ``description``).
A run compares the current values with the snapshot, mails the differences and stores
the new snapshot. The first time a member is seen, only the snapshot is stored.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from heracles.auth.mail import Mailer
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.schema import names as schema
from heracles_plugins._tasks import (
    TaskReport,
    expand_members,
    render_template,
    run_tasks,
    task_filter,
    utc,
)

TASK_CLASS = "hrcTasksNotifications"
TASK_FILTER = task_filter(TASK_CLASS)
SNAPSHOT_PREFIX = "snapshot-"
#: Never monitored: their values are secrets.
FORBIDDEN_ATTRIBUTES = frozenset({"userpassword", "hrcsmbntpassword", "hrcsmblmpassword"})
TEMPLATE_FIELDS = ("uid", "cn", "mail", "changes", "attributes")

type Values = dict[str, list[str]]


def _default_attributes() -> tuple[str, ...]:
    return (
        "mail",
        "sn",
        "givenName",
        "telephoneNumber",
        "mobile",
        "title",
        "employeeType",
        "departmentNumber",
        "l",
        "postalAddress",
        "shadowExpire",
        "manager",
    )


@dataclass(slots=True)
class NotificationsSettings:
    """Settings of the notifications plugin."""

    #: Attributes a task may monitor.
    attributes: tuple[str, ...] = field(default_factory=_default_attributes)


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    """One notification (one changed member) produced by a run."""

    task_dn: str
    user_dn: str
    changes: tuple[str, ...]
    recipients: tuple[str, ...]


@dataclass(slots=True)
class NotificationsReport(TaskReport):
    """What a notifications run did."""

    notifications: list[NotificationRecord] = field(default_factory=lambda: [])
    mails_sent: int = 0
    snapshots_written: int = 0


# --------------------------------------------------------------- snapshots


def _snapshot_dn(task_dn: str, user_dn: str) -> str:
    digest = hashlib.sha256(dnlib.normalize(user_dn).encode()).hexdigest()[:24]
    return f"cn={SNAPSHOT_PREFIX}{digest},{task_dn}"


def load_snapshots(directory: DirectoryClient, task_dn: str) -> dict[str, Values]:
    """Stored snapshots of a task by normalised user DN."""
    out: dict[str, Values] = {}
    try:
        found = list(directory.search(task_dn, "(objectClass=hrcTasks)", Scope.ONE))
    except NoSuchObjectError:
        return out
    for entry in found:
        try:
            data = cast("object", json.loads(entry.text("description") or ""))
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        body = cast("dict[str, Any]", data)
        user, values = body.get("dn"), body.get("values")
        if isinstance(user, str) and isinstance(values, dict):
            raw = cast("dict[str, Any]", values)
            out[dnlib.normalize(user)] = {
                str(k): [str(v) for v in cast("list[Any]", vals)]
                for k, vals in raw.items()
                if isinstance(vals, list)
            }
    return out


def _store_snapshot(directory: DirectoryClient, task_dn: str, user_dn: str, values: Values) -> None:
    dn = _snapshot_dn(task_dn, user_dn)
    payload = json.dumps({"dn": user_dn, "values": values}, sort_keys=True).encode()
    if directory.get(dn, ["objectClass"]) is not None:
        directory.modify(dn, [Modification("replace", "description", [payload])])
        return
    directory.add(
        dn,
        {
            "objectClass": [schema.OC.TASKS.encode()],
            "cn": [dn.split(",", 1)[0].partition("=")[2].encode()],
            "description": [payload],
        },
    )


def delete_snapshots(directory: DirectoryClient, task_dn: str) -> None:
    """Remove every snapshot of a task (before the task is deleted)."""
    try:
        for entry in list(directory.search(task_dn, "(objectClass=hrcTasks)", Scope.ONE)):
            directory.delete(entry.dn)
    except NoSuchObjectError:
        return


# --------------------------------------------------------------------- run


def _current(entry: Entry, attributes: list[str]) -> Values:
    return {a: sorted(entry.texts(a)) for a in attributes if entry.get(a)}


def _diff(old: Values, new: Values, attributes: list[str]) -> list[str]:
    out: list[str] = []
    for name in attributes:
        before, after = old.get(name, []), new.get(name, [])
        if before != after:
            out.append(
                f"{name}: {', '.join(before) or '(empty)'} -> {', '.join(after) or '(empty)'}"
            )
    return out


def monitored_attributes(task: Entry, settings: NotificationsSettings) -> list[str]:
    """The task's attributes that are allowed by the settings (secrets are always dropped)."""
    allowed = {a.lower() for a in settings.attributes} - FORBIDDEN_ATTRIBUTES
    return [
        a
        for a in dict.fromkeys(task.texts("hrcTasksNotificationsAttributes"))
        if a.lower() in allowed
    ]


def _process_task(
    directory: DirectoryClient,
    mailer: Mailer,
    task: Entry,
    settings: NotificationsSettings,
    report: NotificationsReport,
) -> bool:
    attributes = monitored_attributes(task, settings)
    if not attributes:
        report.errors.append(f"{task.dn}: no monitored attribute")
        return False
    template_dn = task.text("hrcTasksNotificationsMailTemplate")
    template = (
        directory.get(
            template_dn, [schema.ATTR.MAIL_TEMPLATE_SUBJECT, schema.ATTR.MAIL_TEMPLATE_BODY]
        )
        if template_dn
        else None
    )
    if template is None:
        report.errors.append(f"{task.dn}: mail template not found")
        return False
    subject_tpl = template.text(schema.ATTR.MAIL_TEMPLATE_SUBJECT) or ""
    body_tpl = template.text(schema.ATTR.MAIL_TEMPLATE_BODY) or ""
    sender = task.text("hrcTasksNotificationsEmailSender") or None
    recipients = [
        mail
        for mail in dict.fromkeys(
            e.text("mail")
            for e in expand_members(directory, task.texts("hrcTasksNotificationsRecipientsMembers"))
        )
        if mail
    ]
    previous = load_snapshots(directory, task.dn)
    seen: set[str] = set()
    for user in expand_members(
        directory, task.texts("hrcTasksNotificationsMonitoredMembers"), attributes
    ):
        key = dnlib.normalize(user.dn)
        seen.add(key)
        values = _current(user, attributes)
        old = previous.get(key)
        if old is not None:
            changes = _diff(old, values, attributes)
            if changes:
                _notify(
                    mailer, task, user, changes, recipients, (subject_tpl, body_tpl, sender), report
                )
        if old != values:
            _store_snapshot(directory, task.dn, user.dn, values)
            report.snapshots_written += 1
    for key in previous.keys() - seen:
        directory.delete(_snapshot_dn(task.dn, key))
    return True


def _notify(
    mailer: Mailer,
    task: Entry,
    user: Entry,
    changes: list[str],
    recipients: list[str],
    template: tuple[str, str, str | None],
    report: NotificationsReport,
) -> None:
    subject_tpl, body_tpl, sender = template
    values = {
        "uid": user.text("uid") or "",
        "cn": user.text("cn") or "",
        "mail": user.text("mail") or "",
        "changes": "\n".join(changes),
        "attributes": ", ".join(c.partition(":")[0] for c in changes),
    }
    subject = render_template(subject_tpl, values)
    body = render_template(body_tpl, values)
    sent: list[str] = []
    for address in recipients:
        try:
            mailer.send(address, subject, body, sender=sender)
        except OSError as exc:
            report.errors.append(f"{task.dn}: mail to {address} failed ({type(exc).__name__})")
            continue
        sent.append(address)
        report.mails_sent += 1
    report.notifications.append(NotificationRecord(task.dn, user.dn, tuple(changes), tuple(sent)))


def run_notifications(
    directory: DirectoryClient,
    mailer: Mailer,
    now: datetime,
    settings: NotificationsSettings | None = None,
) -> NotificationsReport:
    """Run every due notifications task once."""
    settings = settings or NotificationsSettings()
    report = NotificationsReport()
    run_tasks(
        directory,
        TASK_FILTER,
        utc(now),
        lambda task: _process_task(directory, mailer, task, settings, report),
        report,
    )
    return report
