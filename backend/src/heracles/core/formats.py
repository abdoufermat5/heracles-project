"""Named value formats shared by every validator (configuration, admin forms, objects).

Each format is a pure check ``str -> bool``. The browser mirrors them in
``frontend/src/lib/formats.ts`` under the same names, so a value refused by the
form is refused by the server and the other way round. Empty strings are not
checked here: whether a value is required is the caller's decision.
"""

from __future__ import annotations

import re
import zoneinfo
from collections.abc import Callable
from typing import Final, Literal

from heracles.ldap.dn import split
from heracles.ldap.filter import FilterError, parse_filter

type Format = Literal[
    "dn",
    "rdn",
    "abs_path",
    "hostname",
    "domain",
    "port",
    "attribute",
    "ldap_filter",
    "timezone",
    "email",
    "http_header",
    "id_range",
]

#: An LDAP attribute description: a name (letter, then letters, digits, hyphens) or an OID.
_ATTR_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9-]*|[0-9]+(?:\.[0-9]+)+")
_LABEL: Final = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST_RE: Final = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_DOMAIN_RE: Final = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")
_EMAIL_RE: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
#: An HTTP header field name: a token of printable ASCII without separators.
_HEADER_RE: Final = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
#: A numeric identifier ``1100`` or a range ``1100-2000`` (ids fit 32 bits; the upper bound
#: of a range is above its lower bound).
_ID_RANGE_RE: Final = re.compile(r"([0-9]{1,10})(?:-([0-9]{1,10}))?")
_MAX_ID: Final = 2**32 - 1


def _rdn(text: str) -> bool:
    attr, sep, value = text.partition("=")
    return sep == "=" and _ATTR_RE.fullmatch(attr.strip()) is not None and value.strip() != ""


def _raw_parts(text: str) -> list[str]:
    """Parts between unescaped commas, blanks kept (``split`` drops them)."""
    parts: list[str] = []
    cur = ""
    escaped = False
    for ch in text:
        if escaped:
            cur += ch
            escaped = False
        elif ch == "\\":
            cur += ch
            escaped = True
        elif ch == ",":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _dn(text: str) -> bool:
    raw = _raw_parts(text)
    if any(p.strip() == "" for p in raw):
        return False
    try:
        parts = split(text)
    except ValueError:
        return False
    return len(parts) == len(raw) and all(_rdn(p) for p in parts)


def _filter(text: str) -> bool:
    stripped = text.strip()
    if not (stripped.startswith("(") and stripped.endswith(")")):
        return False
    try:
        parse_filter(stripped)
    except FilterError:
        return False
    return True


def _port(text: str) -> bool:
    return text.isdigit() and 1 <= int(text) <= 65535


def _timezone(text: str) -> bool:
    return text in zoneinfo.available_timezones()


def _id_range(text: str) -> bool:
    match = _ID_RANGE_RE.fullmatch(text)
    if match is None:
        return False
    low, high = match.group(1), match.group(2)
    if int(low) > _MAX_ID:
        return False
    return high is None or int(low) < int(high) <= _MAX_ID


_CHECKS: Final[dict[str, Callable[[str], bool]]] = {
    "dn": _dn,
    "rdn": lambda t: "," not in t.replace("\\,", "") and _rdn(t),
    "abs_path": lambda t: t.startswith("/") and "\x00" not in t and not t.endswith("/"),
    "hostname": lambda t: len(t) <= 253 and _HOST_RE.fullmatch(t) is not None,
    "domain": lambda t: len(t) <= 253 and _DOMAIN_RE.fullmatch(t) is not None,
    "port": _port,
    "attribute": lambda t: _ATTR_RE.fullmatch(t) is not None,
    "ldap_filter": _filter,
    "timezone": _timezone,
    "email": lambda t: len(t) <= 254 and _EMAIL_RE.fullmatch(t) is not None,
    "http_header": lambda t: len(t) <= 255 and _HEADER_RE.fullmatch(t) is not None,
    "id_range": _id_range,
}

#: English messages (the API language); the browser shows its own translations.
MESSAGES: Final[dict[str, str]] = {
    "dn": "Expected a distinguished name, such as ou=people,dc=example,dc=com.",
    "rdn": "Expected one RDN, such as ou=people.",
    "abs_path": "Expected an absolute path, such as /bin/bash.",
    "hostname": "Expected a host name.",
    "domain": "Expected a domain name, such as example.com.",
    "port": "Expected a port number between 1 and 65535.",
    "attribute": "Expected an LDAP attribute name.",
    "ldap_filter": "Expected a valid LDAP filter, such as (objectClass=person).",
    "timezone": "Expected a time zone name, such as Europe/Paris.",
    "email": "Expected an e-mail address, such as admin@example.com.",
    "http_header": "Expected an HTTP header name, such as X-Remote-User.",
    "id_range": "Expected a number or a range, such as 1100 or 1100-2000.",
}


def check(fmt: Format | str, value: str) -> str | None:
    """Error message when ``value`` does not match ``fmt``, else ``None`` (empty passes)."""
    if value == "":
        return None
    ok = _CHECKS[fmt](value)
    return None if ok else MESSAGES[fmt]


def register(name: str, matches: Callable[[str], bool], message: str) -> None:
    """Add a format defined outside this module (object attributes, plugins).

    The browser mirrors it by calling ``registerFormat`` under the same name. Registering a
    name twice with a different check is a programming error.
    """
    known = _CHECKS.get(name)
    if known is not None and known is not matches:
        raise ValueError(f"format {name!r} is already registered")
    _CHECKS[name] = matches
    MESSAGES[name] = message
