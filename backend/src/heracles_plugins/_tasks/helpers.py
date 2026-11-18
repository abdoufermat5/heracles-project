"""Small helpers shared by the task plugins: entry readers, dates, templates."""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, timedelta

from heracles.core.generalized_time import parse_generalized_time
from heracles.ldap.client import Entry

EPOCH = date(1970, 1, 1)

STATUS_ACTIVATED = "Activated"
STATUS_DEACTIVATED = "Deactivated"
SCHEDULES = ("hourly", "daily", "weekly", "monthly", "yearly")


_PLACEHOLDER = re.compile(r"\{\{|\}\}|\{(\w+)\}")


def render_template(template: str, values: dict[str, str]) -> str:
    """Fill plain ``{name}`` placeholders; unknown ones and anything else stay verbatim.

    Format specs, attribute access and indexing (``{cn:999999999}``, ``{cn.x}``,
    ``{cn[0]}``) are not interpreted: a template cannot make the server build a huge
    string or reach into objects.
    """

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name is None:  # ``{{`` and ``}}`` are literal braces
            return match.group(0)[0]
        return str(values[name]) if name in values else match.group(0)

    return _PLACEHOLDER.sub(fill, template)


def utc(value: datetime) -> datetime:
    """Aware UTC datetime (naive values are taken as UTC)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def add_months(value: datetime, months: int) -> datetime:
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def next_execution(now: datetime, schedule: str | None) -> datetime | None:
    """Next run after ``now`` for a repeat schedule; ``None`` for an unknown schedule."""
    base = utc(now)
    match (schedule or "").strip().lower():
        case "hourly":
            return base + timedelta(hours=1)
        case "daily":
            return base + timedelta(days=1)
        case "weekly":
            return base + timedelta(weeks=1)
        case "monthly":
            return add_months(base, 1)
        case "yearly":
            return add_months(base, 12)
        case _:
            return None


def bool_of(entry: Entry, attr: str) -> bool | None:
    text = entry.text(attr)
    if text is None:
        return None
    return text.strip().upper() == "TRUE"


def int_of(entry: Entry, attr: str) -> int | None:
    text = entry.text(attr)
    try:
        return int(text.strip()) if text is not None else None
    except ValueError:
        return None


def time_of(entry: Entry, attr: str) -> datetime | None:
    text = entry.text(attr)
    if not text:
        return None
    try:
        return parse_generalized_time(text)
    except ValueError:
        return None


def date_of(entry: Entry, attr: str) -> date | None:
    """A date stored as shadow style epoch days or as a GeneralizedTime."""
    text = (entry.text(attr) or "").strip()
    if not text:
        return None
    if text.isdigit() and len(text) <= 6:
        days = int(text)
        return EPOCH + timedelta(days=days) if days > 0 else None
    try:
        return parse_generalized_time(text).date()
    except ValueError:
        return None


def expiration_of(entry: Entry) -> date | None:
    """Expiration date of an account (``shadowExpire``), or ``None``."""
    days = int_of(entry, "shadowExpire")
    if days is None or days <= 0:
        return None
    return EPOCH + timedelta(days=days)
