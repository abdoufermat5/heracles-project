"""Formats of object attribute values (``format`` attribute constraint).

They extend :mod:`heracles.core.formats` through its registry; the browser mirrors each
one in ``frontend/src/lib/objectFormats.ts`` under the same name, so an attribute value
refused by the editor is refused by the API and the other way round.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from collections.abc import Callable
from typing import Final

from heracles.core.formats import check, register

#: One OpenSSH public key line: optional options, key type, base64 blob, optional comment.
_SSH_KEY_RE: Final = re.compile(
    r'(?:(?:[^\s"]|"(?:[^"\\]|\\.)*")+\s+)?'
    r"(?:disabled-)?"
    r"(?:ssh-(?:dss|rsa|ed25519)|ecdsa-sha2-nistp\d{3}|ecdsa-sk|ed25519-sk|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r"\s+(?P<blob>[A-Za-z0-9+/]+={0,2})"
    r"(?:\s+\S.*)?"
)
_MAC_RE: Final = re.compile(r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{12}")
_SID_RE: Final = re.compile(r"S-1-\d+(?:-\d+)+")
_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f]")


def _ssh_key(text: str) -> bool:
    match = _SSH_KEY_RE.fullmatch(text.strip())
    if match is None:
        return False
    try:
        return bool(base64.b64decode(match["blob"], validate=True))
    except (binascii.Error, ValueError):
        return False


def _ip(version: int | None = None) -> Callable[[str], bool]:
    def check_ip(text: str) -> bool:
        if "%" in text:  # no zone identifiers
            return False
        try:
            found = ipaddress.ip_address(text).version
        except ValueError:
            return False
        return version in (None, found)

    return check_ip


_any_ip: Final = _ip()


def _host_or_ip(text: str) -> bool:
    return _any_ip(text) or check("hostname", text) is None


def _rdn_value(text: str) -> bool:
    return text == text.strip() and _CONTROL_RE.search(text) is None


register(
    "ssh_key", _ssh_key, "Expected an OpenSSH public key, such as ssh-ed25519 AAAA… user@host."
)
register("ip", _any_ip, "Expected an IPv4 or IPv6 address.")
register("ipv4", _ip(4), "Expected an IPv4 address, such as 192.168.1.10.")
register("ipv6", _ip(6), "Expected an IPv6 address, such as 2001:db8::1.")
register(
    "mac",
    lambda t: _MAC_RE.fullmatch(t) is not None,
    "Expected a MAC address, such as aa:bb:cc:dd:ee:ff.",
)
register("host_or_ip", _host_or_ip, "Expected a host name or an IP address.")
register(
    "sid",
    lambda t: _SID_RE.fullmatch(t) is not None,
    "Expected a security identifier, such as S-1-5-21-1-2-3.",
)
register(
    "rdn_value",
    _rdn_value,
    "Must not start or end with a space or contain control characters.",
)
