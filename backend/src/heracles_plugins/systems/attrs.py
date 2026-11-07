"""Attribute kinds specific to system objects: host name, MAC, IP, IMEI, lock mode."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from heracles.attributes import BooleanAttr, StringAttr, ValidationError
from heracles.i18n import _

#: RFC 1123 host name: dot separated labels of 1-63 letters, digits and hyphens.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME_PATTERN = rf"{_LABEL}(?:\.{_LABEL})*"

LOCKED = "locked"
UNLOCKED = "unlocked"

_MAC_RE = re.compile(r"[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}|[0-9a-f]{12}")


def normalize_mac(text: str) -> str | None:
    """Lower-case ``aa:bb:cc:dd:ee:ff`` form of a MAC address, or ``None`` if invalid.

    Accepts ``:`` or ``-`` separated pairs, or twelve bare hexadecimal digits.
    """
    lowered = text.strip().lower()
    if _MAC_RE.fullmatch(lowered) is None:
        return None
    digits = lowered.replace(":", "").replace("-", "")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def normalize_ip(text: str) -> str | None:
    """Canonical text form of an IPv4/IPv6 address, or ``None`` if invalid."""
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        return None


def luhn_valid(digits: str) -> bool:
    """Luhn checksum of a string of decimal digits."""
    if not digits.isascii() or not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


class HostnameAttr(StringAttr):
    """Host name (RFC 1123), at most 253 characters."""

    def __init__(self, name: str, label: str, **kwargs: Any) -> None:
        kwargs.setdefault("pattern", HOSTNAME_PATTERN)
        kwargs.setdefault("max_length", 253)
        super().__init__(name, label, **kwargs)


class MacAttr(StringAttr):
    """MAC address, normalised to lower-case ``aa:bb:cc:dd:ee:ff``."""

    def from_ldap(self, values: list[bytes]) -> str | None:
        text = super().from_ldap(values)
        if text is None:
            return None
        return normalize_mac(text) or text

    def from_json(self, data: object) -> str | None:
        text = super().from_json(data)
        if text is None:
            return None
        mac = normalize_mac(text)
        if mac is None:
            raise ValidationError(_("Invalid MAC address (expected aa:bb:cc:dd:ee:ff)."))
        return mac

    def _validate(self, value: str) -> list[str]:
        if normalize_mac(value) != value:
            return [_("Invalid MAC address (expected aa:bb:cc:dd:ee:ff).")]
        return []


class IpAttr(StringAttr):
    """IPv4 or IPv6 address, stored in canonical text form."""

    def from_json(self, data: object) -> str | None:
        text = super().from_json(data)
        if text is None:
            return None
        ip = normalize_ip(text)
        if ip is None:
            raise ValidationError(_("Invalid IP address."))
        return ip

    def _validate(self, value: str) -> list[str]:
        if normalize_ip(value) is None:
            return [_("Invalid IP address.")]
        return []


class ImeiAttr(StringAttr):
    """IMEI: 15 decimal digits with a valid Luhn check digit."""

    def from_json(self, data: object) -> str | None:
        text = super().from_json(data)
        if text is None:
            return None
        return text.replace(" ", "").replace("-", "") or None

    def _validate(self, value: str) -> list[str]:
        if len(value) != 15 or not value.isascii() or not value.isdigit():
            return [_("An IMEI is made of 15 digits.")]
        if not luhn_valid(value):
            return [_("Invalid IMEI (wrong check digit).")]
        return []


class LockModeAttr(BooleanAttr):
    """Lock flag stored as ``locked`` / ``unlocked`` (absent means unlocked)."""

    def from_ldap(self, values: list[bytes]) -> bool:
        if not values:
            return False
        return values[0].decode("ascii", errors="replace").strip().lower() == LOCKED

    def to_ldap(self, value: bool | None) -> list[bytes]:
        if value is None:
            return []
        return [(LOCKED if value else UNLOCKED).encode("ascii")]
