"""Pure helpers: account flags, logon hours, SIDs and the unix-time date attribute."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from heracles.attributes import DateAttr, StringAttr
from heracles.i18n import _

FLAG_WIDTH = 11
#: Canonical order of the flag letters in ``sambaAcctFlags``.
FLAG_ORDER = "NDHTUMWSLXI"

FLAG_NORMAL = "U"
FLAG_DISABLED = "D"
FLAG_NO_EXPIRE = "X"
FLAG_NEEDS_NO_AUTH = "N"
FLAG_AUTOLOCKED = "L"
FLAG_WORKSTATION = "W"

#: ``sambaPwdLastSet`` value meaning "the password cannot be changed".
PWD_CANNOT_CHANGE = 4294967295
#: ``sambaKickoffTime`` value meaning "never".
KICKOFF_NEVER = 2147483647

LOGON_HOURS_LENGTH = 42
ALL_HOURS = "F" * LOGON_HOURS_LENGTH

_FLAGS_RE = re.compile(r"\[\s*([A-Za-z]*)\s*\]")
_HOURS_RE = re.compile(r"[0-9A-Fa-f]{42}")
_HOST_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}")
_SID_RE = re.compile(r"S-1-\d+(?:-\d+)+")

WELL_KNOWN_GROUPS: tuple[tuple[str, str], ...] = (
    ("512", _("Domain Admins")),
    ("513", _("Domain Users")),
    ("514", _("Domain Guests")),
    ("515", _("Domain Computers")),
    ("516", _("Domain Controllers")),
    ("517", _("Certificate Publishers")),
    ("518", _("Schema Admins")),
    ("519", _("Enterprise Admins")),
    ("520", _("Group Policy Creator Owners")),
    ("544", _("Administrators")),
    ("545", _("Users")),
    ("546", _("Guests")),
    ("547", _("Power Users")),
    ("548", _("Account Operators")),
    ("549", _("Server Operators")),
    ("550", _("Print Operators")),
    ("551", _("Backup Operators")),
    ("552", _("Replicators")),
)
WELL_KNOWN_RIDS = frozenset(int(rid) for rid, _label in WELL_KNOWN_GROUPS)
DOMAIN_USERS_RID = 513
DOMAIN_COMPUTERS_RID = 515


# --------------------------------------------------------------- acct flags


def parse_flags(text: str | None) -> str:
    """Letters of a ``[UX         ]`` flag string (empty when malformed)."""
    if not text:
        return ""
    match = _FLAGS_RE.fullmatch(text.strip())
    return match[1] if match else ""


def format_flags(letters: str) -> str:
    """``[`` + letters padded to 11 characters + ``]``, known letters first in canonical order."""
    unique = dict.fromkeys(letters.replace(" ", ""))
    known = [c for c in FLAG_ORDER if c in unique]
    extra = [c for c in unique if c not in FLAG_ORDER]
    return "[" + "".join(known + extra).ljust(FLAG_WIDTH) + "]"


def set_flag(letters: str, flag: str, on: bool) -> str:
    """Add or remove one letter, preserving every other (including unknown) letters."""
    without = letters.replace(flag, "")
    return without + flag if on else without


# -------------------------------------------------------------- logon hours


def hours_to_grid(value: str | None) -> list[list[bool]]:
    """7 days (Sunday first) x 24 hours of booleans; everything allowed when unset."""
    text = (value or ALL_HOURS).strip()
    if not _HOURS_RE.fullmatch(text):
        text = ALL_HOURS
    raw = bytes.fromhex(text)
    # byte i, bit j (least significant first) is hour 8*i + j of the week
    hours = [bool(raw[i // 8] >> (i % 8) & 1) for i in range(168)]
    return [hours[day * 24 : day * 24 + 24] for day in range(7)]


def grid_to_hours(grid: list[list[bool]]) -> str:
    """Inverse of :func:`hours_to_grid`."""
    flat = [h for day in grid for h in day]
    if len(flat) != 168:
        raise ValueError("expected 7 x 24 values")
    out = bytearray(21)
    for i, on in enumerate(flat):
        if on:
            out[i // 8] |= 1 << (i % 8)
    return out.hex().upper()


class LogonHoursAttr(StringAttr):
    """42 hex characters: one bit per hour of the week, Sunday 00:00 UTC first."""

    def _validate(self, value: str) -> list[str]:
        if not _HOURS_RE.fullmatch(value.strip()):
            return [_("Must be 42 hexadecimal characters (one bit per hour of the week).")]
        return []


class WorkstationsAttr(StringAttr):
    """Comma separated list of workstation names."""

    def _validate(self, value: str) -> list[str]:
        names = [n.strip() for n in value.split(",")]
        if not all(_HOST_RE.fullmatch(n) for n in names):
            return [_("Expected a comma separated list of workstation names.")]
        if len(names) != len({n.lower() for n in names}):
            return [_("Duplicate workstation name.")]
        return []


class SidAttr(StringAttr):
    """A Windows security identifier (``S-1-5-21-...``)."""

    def _validate(self, value: str) -> list[str]:
        if not _SID_RE.fullmatch(value.strip()):
            return [_("Invalid security identifier (expected S-1-5-21-...).")]
        return []


# ------------------------------------------------------------------- times


class UnixDateAttr(DateAttr):
    """A date stored as unix time (seconds, midnight UTC)."""

    def from_ldap(self, values: list[bytes]) -> date | None:
        if not values:
            return None
        text = values[0].decode("ascii", errors="replace").strip()
        if not text.isdigit():
            return None
        seconds = int(text)
        if seconds <= 0 or seconds >= KICKOFF_NEVER:
            return None
        return datetime.fromtimestamp(seconds, UTC).date()

    def to_ldap(self, value: date | None) -> list[bytes]:
        if value is None:
            return []
        moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
        return [str(int(moment.timestamp())).encode("ascii")]


# --------------------------------------------------------------------- SIDs


def is_sid(text: str | None) -> bool:
    return bool(text) and _SID_RE.fullmatch(text or "") is not None


def sid_with_rid(domain_sid: str, rid: int) -> str:
    return f"{domain_sid}-{rid}"


def rid_of(sid: str | None) -> int | None:
    """Last component of a SID."""
    if not sid or not is_sid(sid):
        return None
    return int(sid.rsplit("-", 1)[1])


__all__ = [
    "ALL_HOURS",
    "FLAG_DISABLED",
    "KICKOFF_NEVER",
    "PWD_CANNOT_CHANGE",
    "WELL_KNOWN_GROUPS",
    "LogonHoursAttr",
    "SidAttr",
    "UnixDateAttr",
    "WorkstationsAttr",
    "format_flags",
    "grid_to_hours",
    "hours_to_grid",
    "is_sid",
    "parse_flags",
    "rid_of",
    "set_flag",
    "sid_with_rid",
]
