"""Extractor runner: export attributes of the members as CSV to a file and/or by mail."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from heracles.auth.mail import Mailer
from heracles.ldap.client import DirectoryClient, Entry
from heracles_plugins._tasks import TaskReport, expand_members, run_tasks, task_filter, utc

TASK_CLASS = "fdExtractorTasks"
TASK_FILTER = task_filter(TASK_CLASS)
FORBIDDEN_ATTRIBUTES = frozenset({"userpassword", "sambantpassword", "sambalmpassword"})
FORMATS = {"csv": ",", "tsv": "\t"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _default_attributes() -> tuple[str, ...]:
    return (
        "uid",
        "cn",
        "givenName",
        "sn",
        "mail",
        "telephoneNumber",
        "mobile",
        "title",
        "employeeNumber",
        "employeeType",
        "departmentNumber",
        "l",
        "shadowExpire",
    )


@dataclass(slots=True)
class ExtractorSettings:
    """Settings of the extractor plugin."""

    #: Attributes a task may export.
    attributes: tuple[str, ...] = field(default_factory=_default_attributes)
    #: Directory receiving the files (created when missing); empty disables file output.
    export_directory: str = ""
    #: Subject of the mails; ``{name}`` is the task name.
    mail_subject: str = "Heracles export: {name}"
    #: Separator of the values of a multi-valued attribute.
    value_separator: str = "; "


@dataclass(frozen=True, slots=True)
class ExtractionRecord:
    """One export produced by a run."""

    task_dn: str
    rows: int
    path: str | None
    recipients: tuple[str, ...]


@dataclass(slots=True)
class ExtractorReport(TaskReport):
    """What an extractor run did."""

    extractions: list[ExtractionRecord] = field(default_factory=lambda: [])
    mails_sent: int = 0


def _cell(value: str) -> str:
    """Neutralise spreadsheet formulas."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def render_csv(
    users: list[Entry], attributes: list[str], *, delimiter: str = ",", separator: str = "; "
) -> str:
    """Header plus one row per user; multiple values are joined with ``separator``."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    writer.writerow(attributes)
    for user in users:
        writer.writerow([_cell(separator.join(user.texts(a))) for a in attributes])
    return out.getvalue()


def export_attributes(task: Entry, settings: ExtractorSettings) -> list[str]:
    """The task's attributes allowed by the settings (secrets are always dropped)."""
    allowed = {a.lower() for a in settings.attributes} - FORBIDDEN_ATTRIBUTES
    return [
        a for a in dict.fromkeys(task.texts("fdExtractorTaskAttributes")) if a.lower() in allowed
    ]


def _process_task(
    directory: DirectoryClient,
    mailer: Mailer,
    task: Entry,
    now: datetime,
    settings: ExtractorSettings,
    report: ExtractorReport,
) -> bool:
    attributes = export_attributes(task, settings)
    if not attributes:
        report.errors.append(f"{task.dn}: no exported attribute")
        return False
    recipients = [
        mail
        for mail in dict.fromkeys(
            e.text("mail")
            for e in expand_members(directory, task.texts("fdExtractorRecipientsMembers"))
        )
        if mail
    ]
    if not settings.export_directory and not recipients:
        report.errors.append(f"{task.dn}: no destination (export directory or recipients)")
        return False
    users = expand_members(directory, task.texts("fdExtractorTaskMembers"), attributes)
    users.sort(key=lambda u: (u.text("uid") or "", u.dn))
    fmt = (task.text("fdExtractorTaskFormat") or "csv").lower()
    content = render_csv(
        users,
        attributes,
        delimiter=FORMATS.get(fmt, ","),
        separator=settings.value_separator,
    )
    name = task.text("cn") or "export"
    path: str | None = None
    if settings.export_directory:
        target = Path(settings.export_directory)
        extension = fmt if fmt in FORMATS else "csv"
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        filename = f"{_SAFE_NAME.sub('_', name)}-{stamp}.{extension}"
        try:
            target.mkdir(parents=True, exist_ok=True)
            file = target / filename
            file.write_text(content, encoding="utf-8")
            file.chmod(0o600)
        except OSError as exc:
            report.errors.append(f"{task.dn}: cannot write the export ({type(exc).__name__})")
            return False
        path = str(file)
    sent: list[str] = []
    sender = task.text("fdExtractorEmailSender") or None
    subject = settings.mail_subject.replace("{name}", name)
    for address in recipients:
        try:
            mailer.send(address, subject, content, sender=sender)
        except OSError as exc:
            report.errors.append(f"{task.dn}: mail to {address} failed ({type(exc).__name__})")
            continue
        sent.append(address)
        report.mails_sent += 1
    report.extractions.append(ExtractionRecord(task.dn, len(users), path, tuple(sent)))
    return True


def run_extractor(
    directory: DirectoryClient,
    mailer: Mailer,
    now: datetime,
    settings: ExtractorSettings | None = None,
) -> ExtractorReport:
    """Run every due extractor task once."""
    settings = settings or ExtractorSettings()
    now = utc(now)
    report = ExtractorReport()
    run_tasks(
        directory,
        TASK_FILTER,
        now,
        lambda task: _process_task(directory, mailer, task, now, settings, report),
        report,
    )
    return report
