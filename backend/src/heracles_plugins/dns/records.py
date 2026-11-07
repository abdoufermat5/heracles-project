"""Pure DNS helpers: record syntax, SOA handling, serial numbers, reverse names."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from heracles.i18n import _

#: Record type -> LDAP attribute of the ``dNSZone`` object class.
RECORD_ATTRS: Mapping[str, str] = {
    "A": "aRecord",
    "AAAA": "aAAARecord",
    "CNAME": "cNAMERecord",
    "MX": "mXRecord",
    "NS": "nSRecord",
    "PTR": "pTRRecord",
    "SRV": "sRVRecord",
    "TXT": "tXTRecord",
    "CAA": "cAARecord",
    "SSHFP": "sSHFPRecord",
    "NAPTR": "nAPTRRecord",
    "DS": "dSRecord",
    "CERT": "certRecord",
    "KX": "kXRecord",
    "AFSDB": "aFSDBRecord",
    "LOC": "LocRecord",
    "KEY": "KeyRecord",
    "SIG": "SigRecord",
    "RRSIG": "rRSIGRecord",
    "NSEC": "nSECRecord",
    "HINFO": "hInfoRecord",
}

#: Structured helpers stored as ``tXTRecord`` values (value prefix of each).
PSEUDO_TYPES: Mapping[str, str] = {
    "SPF": "v=spf1",
    "DKIM": "v=DKIM1",
    "DMARC": "v=DMARC1",
}

RECORD_TYPES: tuple[str, ...] = (*RECORD_ATTRS, *PSEUDO_TYPES)
RECORD_ATTR_NAMES: tuple[str, ...] = tuple(RECORD_ATTRS.values())
_TYPE_BY_ATTR = {attr.lower(): rtype for rtype, attr in RECORD_ATTRS.items()}
#: Types whose value is (or ends with) a host name.
_HOST_LAST = {"CNAME", "NS", "PTR", "MX", "SRV", "KX", "AFSDB"}

_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?"
HOST_RE = re.compile(rf"(?:\*\.)?{_LABEL}(?:\.{_LABEL})*\.?")
NAME_RE = re.compile(rf"@|\*|(?:\*\.)?{_LABEL}(?:\.{_LABEL})*")
ZONE_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
REVERSE_RE = re.compile(rf"(?:{_LABEL}\.)+(?:in-addr|ip6)\.arpa\.?", re.IGNORECASE)
_MAIL_RE = re.compile(r"(?:[^\s.\\]|\\\.)+(?:\.(?:[^\s.\\]|\\\.)+)*\.?")


def type_to_attr(rtype: str) -> str:
    """LDAP attribute that stores records of ``rtype`` (pseudo types use TXT)."""
    return RECORD_ATTRS.get(rtype, "tXTRecord")


def classify(attr: str, value: str) -> str | None:
    """Record type of one attribute value (``None`` for non-record attributes)."""
    rtype = _TYPE_BY_ATTR.get(attr.lower())
    if rtype == "TXT":
        for pseudo, prefix in PSEUDO_TYPES.items():
            if value.strip().lower().startswith(prefix.lower()):
                return pseudo
    return rtype


# ------------------------------------------------------------------ hostnames


def normalize_host(host: str, final_dot: bool) -> str:
    """Write a host name with (or without) its trailing dot.

    Single-label names are relative to the zone origin and are left untouched
    when a final dot is wanted.
    """
    text = host.strip()
    if text in ("", ".", "@"):
        return text
    bare = text.rstrip(".")
    if final_dot:
        return bare + "." if "." in bare else text
    return bare


def normalize_value(rtype: str, value: str, final_dot: bool) -> str:
    """Normalise whitespace and the final dot of host names in a record value."""
    if rtype not in _HOST_LAST:
        return value.strip()
    tokens = value.split()
    if not tokens:
        return ""
    tokens[-1] = normalize_host(tokens[-1], final_dot)
    return " ".join(tokens)


def normalize_mail(value: str) -> str:
    """SOA mailbox in zone-file form; an email address has its ``@`` turned into a dot."""
    text = value.strip()
    if "@" in text:
        local, _sep, domain = text.rpartition("@")
        text = local.replace(".", "\\.") + "." + domain
    return text


def fqdn(name: str, zone: str, final_dot: bool) -> str:
    """Full name of ``name`` (``@`` = apex) inside ``zone``."""
    full = zone if name == "@" else f"{name}.{zone}"
    return normalize_host(full, final_dot)


# ----------------------------------------------------------------- validation

_INT = r"\d{1,10}"
_WORD = r'(?:"[^"]*"|\S+)'


def _uint(text: str, maximum: int) -> bool:
    return text.isdigit() and int(text) <= maximum


def _host_ok(text: str) -> bool:
    return text == "." or HOST_RE.fullmatch(text) is not None


def _check_ip(version: int) -> Callable[[str], bool]:
    def check(value: str) -> bool:
        try:
            return ipaddress.ip_address(value).version == version
        except ValueError:
            return False

    return check


def _pref_host(value: str) -> bool:
    parts = value.split()
    return len(parts) == 2 and _uint(parts[0], 65535) and _host_ok(parts[1])


def _srv(value: str) -> bool:
    parts = value.split()
    return len(parts) == 4 and all(_uint(p, 65535) for p in parts[:3]) and _host_ok(parts[3])


def _regex(pattern: str) -> Callable[[str], bool]:
    compiled = re.compile(pattern)
    return lambda value: compiled.fullmatch(value.strip()) is not None


def _nonempty(value: str) -> bool:
    return bool(value.strip())


_CHECKS: Mapping[str, tuple[Callable[[str], bool], str]] = {
    "A": (_check_ip(4), _("Expected an IPv4 address.")),
    "AAAA": (_check_ip(6), _("Expected an IPv6 address.")),
    "CNAME": (_host_ok, _("Expected a host name.")),
    "NS": (_host_ok, _("Expected a host name.")),
    "PTR": (_host_ok, _("Expected a host name.")),
    "MX": (_pref_host, _("Expected '<preference> <host>'.")),
    "KX": (_pref_host, _("Expected '<preference> <host>'.")),
    "AFSDB": (_pref_host, _("Expected '<subtype> <host>'.")),
    "SRV": (_srv, _("Expected '<priority> <weight> <port> <target>'.")),
    "TXT": (_nonempty, _("A text value is required.")),
    "CAA": (
        _regex(rf"\d{{1,3}} [A-Za-z0-9]+ {_WORD}"),
        _("Expected '<flags> <tag> \"<value>\"'."),
    ),
    "SSHFP": (
        _regex(r"\d{1,3} \d{1,3} [0-9A-Fa-f]+"),
        _("Expected '<algorithm> <type> <fingerprint>'."),
    ),
    "NAPTR": (
        _regex(rf'{_INT} {_INT} "[^"]*" "[^"]*" "[^"]*" \S+'),
        _('Expected \'<order> <preference> "<flags>" "<service>" "<regexp>" <replacement>\'.'),
    ),
    "DS": (
        _regex(r"\d{1,5} \d{1,3} \d{1,3} [0-9A-Fa-f]+"),
        _("Expected '<key tag> <algorithm> <digest type> <digest>'."),
    ),
    "CERT": (
        _regex(r"\S+ \d{1,5} \S+ \S+"),
        _("Expected '<type> <key tag> <algorithm> <certificate>'."),
    ),
    "HINFO": (_regex(rf"{_WORD} {_WORD}"), _("Expected '<cpu> <os>'.")),
    "LOC": (_nonempty, _("A value is required.")),
    "KEY": (_nonempty, _("A value is required.")),
    "SIG": (_nonempty, _("A value is required.")),
    "RRSIG": (_nonempty, _("A value is required.")),
    "NSEC": (_nonempty, _("A value is required.")),
}


def validate_record(name: str, rtype: str, value: str) -> str | None:
    """Problem with one record, or ``None`` when it is valid."""
    if rtype in PSEUDO_TYPES:
        if not value.strip().lower().startswith(PSEUDO_TYPES[rtype].lower()):
            return _("The value must start with '{prefix}'.").format(prefix=PSEUDO_TYPES[rtype])
        lowered = name.lower()
        if rtype == "DKIM" and not lowered.endswith("._domainkey"):
            return _("The name of a DKIM record must be '<selector>._domainkey'.")
        if rtype == "DMARC" and lowered != "_dmarc":
            return _("The name of a DMARC record must be '_dmarc'.")
        return None
    check = _CHECKS.get(rtype)
    if check is None:
        return _("Unknown record type.")
    ok, message = check
    return None if ok(value.strip()) else message


@dataclass(frozen=True, slots=True)
class Record:
    """One resource record of a zone (``name`` ``@`` is the apex)."""

    name: str
    type: str
    value: str


def validate_records(records: Sequence[Record]) -> list[str]:
    """Cross-record problems: CNAME conflicts and apex restrictions."""
    problems: list[str] = []
    by_name: dict[str, list[tuple[int, Record]]] = {}
    for index, rec in enumerate(records, start=1):
        by_name.setdefault(rec.name.casefold(), []).append((index, rec))
    for group in by_name.values():
        cnames = [(i, r) for i, r in group if r.type == "CNAME"]
        if not cnames:
            continue
        index, rec = cnames[0]
        if rec.name == "@":
            problems.append(_("Record {n}: a CNAME cannot be set on the apex.").format(n=index))
        elif len(cnames) > 1:
            problems.append(
                _("Record {n}: '{name}' can only have one CNAME.").format(
                    n=cnames[1][0], name=rec.name
                )
            )
        elif len(group) > 1:
            other = next(i for i, r in group if r.type != "CNAME")
            problems.append(
                _("Record {n}: '{name}' has a CNAME and cannot hold other records.").format(
                    n=other, name=rec.name
                )
            )
    return problems


# ------------------------------------------------------------------- SOA, TTL


@dataclass(frozen=True, slots=True)
class Soa:
    """Fields of a start of authority record."""

    primary: str
    mail: str
    serial: str
    refresh: int
    retry: int
    expire: int
    minimum: int

    def format(self) -> str:
        return (
            f"{self.primary} {self.mail} {self.serial} "
            f"{self.refresh} {self.retry} {self.expire} {self.minimum}"
        )


def parse_soa(text: str | None) -> Soa | None:
    """Parse an ``sOARecord`` value; ``None`` when malformed."""
    if not text:
        return None
    parts = text.split()
    if len(parts) != 7 or not all(p.isdigit() for p in parts[2:]):
        return None
    return Soa(
        parts[0], parts[1], parts[2], int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
    )


def valid_mailbox(text: str) -> bool:
    return _MAIL_RE.fullmatch(text) is not None


def next_serial(current: str | None, today: date) -> str:
    """``YYYYMMDD01``, or the current serial plus one when it is not older than that."""
    candidate = int(today.strftime("%Y%m%d") + "01")
    if current and current.isdigit() and int(current) >= candidate:
        return str(int(current) + 1)
    return str(candidate)


# --------------------------------------------------------------- reverse zones


def reverse_relative(address: str, reverse_zone: str) -> str | None:
    """Name of ``address`` relative to ``reverse_zone`` (``None`` when outside of it)."""
    try:
        pointer = ipaddress.ip_address(address.strip()).reverse_pointer.lower()
    except ValueError:
        return None
    zone = reverse_zone.lower().rstrip(".")
    if pointer.endswith("." + zone):
        return pointer[: -len(zone) - 1]
    return None


# ------------------------------------------------------------------ TXT helpers


def build_spf(mechanisms: Sequence[str], default: str = "~all") -> str:
    """``v=spf1 <mechanisms> <default>`` (SPF helper, stored as TXT)."""
    return " ".join(["v=spf1", *(m.strip() for m in mechanisms if m.strip()), default])


def build_dkim(public_key: str, key_type: str = "rsa", flags: str = "") -> str:
    """``v=DKIM1; k=rsa; p=<key>`` (DKIM helper, stored as TXT on ``<selector>._domainkey``)."""
    parts = ["v=DKIM1", f"k={key_type}", f"p={public_key.strip()}"]
    if flags:
        parts.append(f"t={flags}")
    return "; ".join(parts)


def build_dmarc(policy: str = "none", rua: str | None = None, pct: int | None = None) -> str:
    """``v=DMARC1; p=<policy>; ...`` (DMARC helper, stored as TXT on ``_dmarc``)."""
    parts = ["v=DMARC1", f"p={policy}"]
    if rua:
        parts.append(f"rua={rua}")
    if pct is not None:
        parts.append(f"pct={pct}")
    return "; ".join(parts)
