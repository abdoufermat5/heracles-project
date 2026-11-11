"""Reminder runner: find expiring accounts and mail them.

:func:`run_reminders` is a pure function of a directory, a mailer and a clock,
so it can be called from anywhere. The planned CLI sub-command (for example
``heracles reminders run``) and the scheduler (cron or a periodic task) both
only have to build a ``DirectoryClient`` and a ``Mailer`` and call::

    report = run_reminders(directory, mailer, datetime.now(UTC), base_url, settings)

It is idempotent for a given instant: a task that ran is rescheduled (or
deactivated) so a second call right after sends nothing.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import structlog

from heracles.auth.mail import Mailer
from heracles.core.containers import ensure_container
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    Entry,
    NoSuchObjectError,
)
from heracles.ldap.filter import escape_filter_value
from heracles.schema import names as schema
from heracles_plugins._tasks import (
    EPOCH,
    SCHEDULES,
    STATUS_ACTIVATED,
    STATUS_DEACTIVATED,
    TASKS_RDN,
    TaskReport,
    bool_of,
    expand_members,
    expiration_of,
    int_of,
    next_execution,
    render_template,
    run_tasks,
    task_filter,
    utc,
)

log = structlog.get_logger(__name__)

TASK_FILTER = task_filter("hrcTasksReminder")
TOKEN_TYPE_REMINDER = "reminder"  # noqa: S105
REMINDER_TOKENS_RDN = f"ou=reminder,{schema.RDN.TOKENS}"

TEMPLATE_FIELDS = (
    "uid",
    "cn",
    "givenName",
    "sn",
    "mail",
    "expiration_date",
    "days_left",
    "prolongation_url",
)


@dataclass(frozen=True, slots=True)
class ReminderRecord:
    """One reminder produced by a run."""

    task_dn: str
    user_dn: str
    days_left: int
    recipients: tuple[str, ...]


@dataclass(slots=True)
class RunReport(TaskReport):
    """What a run did."""

    reminders: list[ReminderRecord] = field(default_factory=lambda: [])
    mails_sent: int = 0
    tokens_created: int = 0


# ------------------------------------------------------------------ helpers


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ tokens


def reminder_tokens_container(directory: DirectoryClient) -> str:
    return dnlib.join(REMINDER_TOKENS_RDN, directory.base_dn)


def create_prolongation_token(
    directory: DirectoryClient, user_dn: str, *, now: datetime, valid_days: int
) -> str:
    """Store a single-use token (hashed) for ``user_dn`` and return the clear value.

    ``hrcTokenTimestamp`` holds the instant (epoch seconds) until which the token is valid.
    A previous reminder token of the same user is replaced.
    """
    container = reminder_tokens_container(directory)
    ensure_container(directory, container)
    flt = (
        f"(&(objectClass={schema.OC.TOKEN})({schema.ATTR.TOKEN_TYPE}={TOKEN_TYPE_REMINDER})"
        f"({schema.ATTR.TOKEN_USER_DN}={escape_filter_value(user_dn)}))"
    )
    try:
        for old in list(directory.search(container, flt, attrs=[schema.ATTR.TOKEN_USER_DN])):
            if dnlib.normalize(old.text(schema.ATTR.TOKEN_USER_DN) or "") == dnlib.normalize(
                user_dn
            ):
                directory.delete(old.dn)
    except NoSuchObjectError:
        pass
    token = secrets.token_urlsafe(32)
    hashed = hash_token(token)
    expires = int(utc(now).timestamp()) + valid_days * 86400
    directory.add(
        f"cn={hashed},{container}",
        {
            "objectClass": [schema.OC.TOKEN.encode()],
            "cn": [hashed.encode()],
            schema.ATTR.TOKEN: [hashed.encode()],
            schema.ATTR.TOKEN_TYPE: [TOKEN_TYPE_REMINDER.encode()],
            schema.ATTR.TOKEN_USER_DN: [user_dn.encode()],
            schema.ATTR.TOKEN_TIMESTAMP: [str(expires).encode()],
        },
    )
    return token


# ------------------------------------------------------------------ runner


def _accepts(task: Entry) -> bool:
    return bool_of(task, "hrcTasksReminderPosix") is not False


def _template_of(directory: DirectoryClient, task: Entry) -> tuple[str, str] | None:
    dn = task.text("hrcTasksReminderMailTemplate")
    if not dn:
        return None
    entry = directory.get(dn, [schema.ATTR.MAIL_TEMPLATE_SUBJECT, schema.ATTR.MAIL_TEMPLATE_BODY])
    if entry is None:
        return None
    return (
        entry.text(schema.ATTR.MAIL_TEMPLATE_SUBJECT) or "",
        entry.text(schema.ATTR.MAIL_TEMPLATE_BODY) or "",
    )


def _process_task(
    directory: DirectoryClient,
    mailer: Mailer,
    task: Entry,
    now: datetime,
    base_url: str,
    report: RunReport,
) -> bool:
    template = _template_of(directory, task)
    if template is None:
        report.errors.append(f"{task.dn}: mail template not found")
        return False
    subject_tpl, body_tpl = template
    first = int_of(task, "hrcTasksReminderFirstCall")
    second = int_of(task, "hrcTasksReminderSecondCall")
    calls = {c for c in (first, second) if c is not None}
    prolong = bool_of(task, "hrcTasksReminderAccountProlongation") is True
    valid_days = max(second if second is not None else (first or 0), 1)
    today = utc(now).date()
    copies = {
        e.text("mail"): e
        for e in expand_members(directory, task.texts("hrcTasksReminderRecipientsMembers"))
        if e.text("mail")
    }
    sender = task.text("hrcTasksReminderEmailSender") or None
    for user in expand_members(directory, task.texts("hrcTasksReminderMembers")):
        expires = expiration_of(user)
        if expires is None:
            continue
        days_left = (expires - today).days
        if days_left not in calls:
            continue
        values = {
            "uid": user.text("uid") or "",
            "cn": user.text("cn") or "",
            "givenName": user.text("givenName") or "",
            "sn": user.text("sn") or "",
            "mail": user.text("mail") or "",
            "expiration_date": expires.isoformat(),
            "days_left": str(days_left),
            "prolongation_url": "",
        }
        if prolong:
            token = create_prolongation_token(directory, user.dn, now=now, valid_days=valid_days)
            report.tokens_created += 1
            values["prolongation_url"] = (
                f"{base_url.rstrip('/')}/reminder/prolong"
                f"?login={quote(values['uid'], safe='')}&token={quote(token, safe='')}"
            )
        subject = render_template(subject_tpl, values)
        body = render_template(body_tpl, values)
        addresses: list[str] = []
        for address in [user.text("mail"), *copies]:
            if address and address.lower() not in {a.lower() for a in addresses}:
                addresses.append(address)
        for address in addresses:
            try:
                mailer.send(address, subject, body, sender=sender)
            except OSError as exc:
                report.errors.append(f"{task.dn}: mail to {address} failed ({type(exc).__name__})")
                continue
            report.mails_sent += 1
        report.reminders.append(ReminderRecord(task.dn, user.dn, days_left, tuple(addresses)))
    return True


def run_reminders(
    directory: DirectoryClient,
    mailer: Mailer,
    now: datetime,
    base_url: str,
    settings: Any = None,
) -> RunReport:
    """Run every due, activated reminder task once.

    ``settings`` is the plugin settings object (``registry.settings["user_reminder"]``);
    it is accepted for symmetry with the other entry points and for future options.
    """
    del settings
    report = RunReport()
    run_tasks(
        directory,
        TASK_FILTER,
        now,
        lambda task: _process_task(directory, mailer, task, utc(now), base_url, report),
        report,
        accept=_accepts,
    )
    return report


def utcnow() -> datetime:
    return datetime.fromtimestamp(time.time(), UTC)


__all__ = [
    "EPOCH",
    "REMINDER_TOKENS_RDN",
    "SCHEDULES",
    "STATUS_ACTIVATED",
    "STATUS_DEACTIVATED",
    "TASKS_RDN",
    "TASK_FILTER",
    "TEMPLATE_FIELDS",
    "TOKEN_TYPE_REMINDER",
    "ReminderRecord",
    "RunReport",
    "create_prolongation_token",
    "expand_members",
    "expiration_of",
    "hash_token",
    "next_execution",
    "reminder_tokens_container",
    "render_template",
    "run_reminders",
    "utcnow",
]
