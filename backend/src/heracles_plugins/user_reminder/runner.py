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

import calendar
import hashlib
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import structlog

from heracles.auth.mail import Mailer
from heracles.core.containers import ensure_container
from heracles.core.generalized_time import format_generalized_time, parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
)
from heracles.ldap.filter import escape_filter_value
from heracles.schema import legacy

log = structlog.get_logger(__name__)

TASKS_RDN = "ou=tasks"
TASK_FILTER = "(&(objectClass=fdTasks)(objectClass=fdTasksReminder))"
TOKEN_TYPE_REMINDER = "reminder"  # noqa: S105
REMINDER_TOKENS_RDN = f"ou=reminder,{legacy.RDN.TOKENS}"
STATUS_ACTIVATED = "Activated"
STATUS_DEACTIVATED = "Deactivated"
SCHEDULES = ("hourly", "daily", "weekly", "monthly", "yearly")
EPOCH = date(1970, 1, 1)

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

_USER_ATTRS = [
    "objectClass",
    "uid",
    "cn",
    "givenName",
    "sn",
    "mail",
    "shadowExpire",
    "member",
    "roleOccupant",
]


@dataclass(frozen=True, slots=True)
class ReminderRecord:
    """One reminder produced by a run."""

    task_dn: str
    user_dn: str
    days_left: int
    recipients: tuple[str, ...]


@dataclass(slots=True)
class RunReport:
    """What a run did."""

    tasks_examined: int = 0
    tasks_run: int = 0
    reminders: list[ReminderRecord] = field(default_factory=lambda: [])
    mails_sent: int = 0
    tokens_created: int = 0
    errors: list[str] = field(default_factory=lambda: [])


# ------------------------------------------------------------------ helpers


class _SafeDict(dict[str, str]):
    """Unknown placeholders are kept as they are."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template(template: str, values: dict[str, str]) -> str:
    """Fill ``{placeholders}``; unknown ones stay, malformed templates are kept verbatim."""
    mapping = _SafeDict({k: str(v) for k, v in values.items()})
    try:
        return template.format_map(mapping)
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        return template


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _add_months(value: datetime, months: int) -> datetime:
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def next_execution(now: datetime, schedule: str | None) -> datetime | None:
    """Next run after ``now`` for a repeat schedule; ``None`` for an unknown schedule."""
    base = _utc(now)
    match (schedule or "").strip().lower():
        case "hourly":
            return base + timedelta(hours=1)
        case "daily":
            return base + timedelta(days=1)
        case "weekly":
            return base + timedelta(weeks=1)
        case "monthly":
            return _add_months(base, 1)
        case "yearly":
            return _add_months(base, 12)
        case _:
            return None


def _bool(entry: Entry, attr: str) -> bool | None:
    text = entry.text(attr)
    if text is None:
        return None
    return text.strip().upper() == "TRUE"


def _int(entry: Entry, attr: str) -> int | None:
    text = entry.text(attr)
    try:
        return int(text.strip()) if text is not None else None
    except ValueError:
        return None


def _time(entry: Entry, attr: str) -> datetime | None:
    text = entry.text(attr)
    if not text:
        return None
    try:
        return parse_generalized_time(text)
    except ValueError:
        return None


def expiration_of(entry: Entry) -> date | None:
    """Expiration date of an account (``shadowExpire``), or ``None``."""
    days = _int(entry, "shadowExpire")
    if days is None or days <= 0:
        return None
    return EPOCH + timedelta(days=days)


# ---------------------------------------------------------------- members


def expand_members(directory: DirectoryClient, dns: Iterable[str]) -> list[Entry]:
    """Resolve DNs of users, groups (``member``) and roles (``roleOccupant``) to user entries.

    Nested groups are followed; every user appears once.
    """
    users: dict[str, Entry] = {}
    seen: set[str] = set()
    pending = list(dns)
    while pending:
        dn = pending.pop(0)
        key = dnlib.normalize(dn)
        if key in seen:
            continue
        seen.add(key)
        try:
            entry = directory.get(dn, _USER_ATTRS)
        except DirectoryError:
            continue
        if entry is None:
            continue
        if entry.has_object_class("organizationalRole"):
            pending.extend(entry.texts("roleOccupant"))
        elif entry.has_object_class("groupOfNames") or entry.has_object_class(
            legacy.OC.OBJECT_GROUP
        ):
            pending.extend(entry.texts("member"))
        else:
            users[key] = entry
    return list(users.values())


# ------------------------------------------------------------------ tokens


def reminder_tokens_container(directory: DirectoryClient) -> str:
    return dnlib.join(REMINDER_TOKENS_RDN, directory.base_dn)


def create_prolongation_token(
    directory: DirectoryClient, user_dn: str, *, now: datetime, valid_days: int
) -> str:
    """Store a single-use token (hashed) for ``user_dn`` and return the clear value.

    ``fdTokenTimestamp`` holds the instant (epoch seconds) until which the token is valid.
    A previous reminder token of the same user is replaced.
    """
    container = reminder_tokens_container(directory)
    ensure_container(directory, container)
    flt = (
        f"(&(objectClass={legacy.OC.TOKEN})({legacy.ATTR.TOKEN_TYPE}={TOKEN_TYPE_REMINDER})"
        f"({legacy.ATTR.TOKEN_USER_DN}={escape_filter_value(user_dn)}))"
    )
    try:
        for old in list(directory.search(container, flt, attrs=[legacy.ATTR.TOKEN_USER_DN])):
            if dnlib.normalize(old.text(legacy.ATTR.TOKEN_USER_DN) or "") == dnlib.normalize(
                user_dn
            ):
                directory.delete(old.dn)
    except NoSuchObjectError:
        pass
    token = secrets.token_urlsafe(32)
    hashed = hash_token(token)
    expires = int(_utc(now).timestamp()) + valid_days * 86400
    directory.add(
        f"cn={hashed},{container}",
        {
            "objectClass": [legacy.OC.TOKEN.encode()],
            "cn": [hashed.encode()],
            legacy.ATTR.TOKEN: [hashed.encode()],
            legacy.ATTR.TOKEN_TYPE: [TOKEN_TYPE_REMINDER.encode()],
            legacy.ATTR.TOKEN_USER_DN: [user_dn.encode()],
            legacy.ATTR.TOKEN_TIMESTAMP: [str(expires).encode()],
        },
    )
    return token


# ------------------------------------------------------------------ runner


def _tasks(directory: DirectoryClient) -> list[Entry]:
    try:
        return list(directory.search(dnlib.join(TASKS_RDN, directory.base_dn), TASK_FILTER))
    except NoSuchObjectError:
        return []


def _is_due(task: Entry, now: datetime) -> bool:
    status = (task.text("fdTasksStatus") or "").strip().lower()
    if status != STATUS_ACTIVATED.lower():
        return False
    if _bool(task, "fdTasksReminderPosix") is False:
        return False
    next_exec = _time(task, "fdTasksNextExec")
    return next_exec is None or next_exec <= now


def _template_of(directory: DirectoryClient, task: Entry) -> tuple[str, str] | None:
    dn = task.text("fdTasksReminderMailTemplate")
    if not dn:
        return None
    entry = directory.get(dn, [legacy.ATTR.MAIL_TEMPLATE_SUBJECT, legacy.ATTR.MAIL_TEMPLATE_BODY])
    if entry is None:
        return None
    return (
        entry.text(legacy.ATTR.MAIL_TEMPLATE_SUBJECT) or "",
        entry.text(legacy.ATTR.MAIL_TEMPLATE_BODY) or "",
    )


def _reschedule(directory: DirectoryClient, task: Entry, now: datetime) -> str | None:
    """Update last/next execution; returns an error message for a bad schedule."""
    repeatable = _bool(task, "fdTasksRepeatable") is True
    changes = [
        Modification("replace", "fdTasksLastExec", [format_generalized_time(now).encode()]),
    ]
    error: str | None = None
    following = next_execution(now, task.text("fdTasksRepeatableSchedule")) if repeatable else None
    if repeatable and following is None:
        error = f"{task.dn}: unknown repeat schedule, task deactivated"
    if following is not None:
        changes.append(
            Modification(
                "replace", "fdTasksNextExec", [format_generalized_time(following).encode()]
            )
        )
    else:
        if task.get("fdTasksNextExec"):
            changes.append(Modification("delete", "fdTasksNextExec"))
        changes.append(Modification("replace", "fdTasksStatus", [STATUS_DEACTIVATED.encode()]))
    directory.modify(task.dn, changes)
    return error


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
    first = _int(task, "fdTasksReminderFirstCall")
    second = _int(task, "fdTasksReminderSecondCall")
    calls = {c for c in (first, second) if c is not None}
    prolong = _bool(task, "fdTasksReminderAccountProlongation") is True
    valid_days = max(second if second is not None else (first or 0), 1)
    today = _utc(now).date()
    copies = {
        e.text("mail"): e
        for e in expand_members(directory, task.texts("fdTasksReminderRecipientsMembers"))
        if e.text("mail")
    }
    sender = task.text("fdTasksReminderEmailSender") or None
    for user in expand_members(directory, task.texts("fdTasksReminderMembers")):
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
    now = _utc(now)
    report = RunReport()
    for task in _tasks(directory):
        report.tasks_examined += 1
        if not _is_due(task, now):
            continue
        try:
            done = _process_task(directory, mailer, task, now, base_url, report)
            if not done:
                continue
            error = _reschedule(directory, task, now)
        except DirectoryError as exc:
            report.errors.append(f"{task.dn}: {type(exc).__name__}")
            log.warning("reminder_task_failed", task=task.dn, error=type(exc).__name__)
            continue
        if error:
            report.errors.append(error)
        report.tasks_run += 1
    return report


def utcnow() -> datetime:
    return datetime.fromtimestamp(time.time(), UTC)
