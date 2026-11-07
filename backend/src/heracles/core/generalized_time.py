"""LDAP GeneralizedTime (RFC 4517) parsing and formatting."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

_PATTERN = re.compile(
    r"^(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})(?P<h>\d{2})(?P<mi>\d{2})?(?P<s>\d{2})?"
    r"(?:[.,](?P<frac>\d+))?(?P<tz>Z|[+-]\d{2}(?:\d{2})?)?$"
)


def format_generalized_time(value: datetime) -> str:
    """Format as ``YYYYmmddHHMMSSZ`` in UTC (naive datetimes are taken as UTC)."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime("%Y%m%d%H%M%S") + "Z"


def parse_generalized_time(text: str) -> datetime:
    """Parse a GeneralizedTime string into an aware datetime.

    Values without a zone designator are interpreted as UTC. Fractions apply to
    the least significant time component present.
    """
    match = _PATTERN.match(text.strip())
    if match is None:
        raise ValueError(f"invalid GeneralizedTime: {text!r}")
    minute = match["mi"]
    second = match["s"]
    if second is not None and minute is None:
        raise ValueError(f"invalid GeneralizedTime: {text!r}")
    try:
        base = datetime(
            int(match["y"]),
            int(match["mo"]),
            int(match["d"]),
            int(match["h"]),
            int(minute or 0),
            int(second or 0),
            tzinfo=UTC,
        )
    except ValueError as exc:
        raise ValueError(f"invalid GeneralizedTime: {text!r}") from exc
    frac = match["frac"]
    if frac:
        fraction = float("0." + frac)
        unit = (
            timedelta(seconds=1)
            if second is not None
            else (timedelta(minutes=1) if minute is not None else timedelta(hours=1))
        )
        base += unit * fraction
    tz = match["tz"]
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:]
        offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:] or 0))
        # The wall-clock time was local to the offset; convert it to UTC.
        zone = timezone(sign * offset)
        base = base.replace(tzinfo=zone).astimezone(UTC)
    return base
