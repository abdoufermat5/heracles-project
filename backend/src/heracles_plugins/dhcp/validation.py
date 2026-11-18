"""Validation and normalization helpers for DHCP sections."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence

from heracles.i18n import _
from heracles.ldap.client import Entry

MAC_RE = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$")

ALLOWED_CHILDREN_BY_CLASS: dict[str, frozenset[str]] = {
    "dhcpService": frozenset(
        {
            "dhcpSharedNetwork",
            "dhcpSubnet",
            "dhcpGroup",
            "dhcpHost",
            "dhcpClass",
            "dhcpTSigKey",
            "dhcpDnsZone",
            "dhcpFailOverPeer",
        }
    ),
    "dhcpSharedNetwork": frozenset(
        {
            "dhcpSubnet",
            "dhcpPool",
            "dhcpTSigKey",
            "dhcpDnsZone",
            "dhcpFailOverPeer",
        }
    ),
    "dhcpSubnet": frozenset(
        {
            "dhcpPool",
            "dhcpGroup",
            "dhcpHost",
            "dhcpClass",
            "dhcpTSigKey",
            "dhcpDnsZone",
            "dhcpFailOverPeer",
        }
    ),
    "dhcpGroup": frozenset(
        {
            "dhcpHost",
        }
    ),
    "dhcpClass": frozenset(
        {
            "dhcpSubClass",
        }
    ),
    "dhcpPool": frozenset(),
    "dhcpHost": frozenset(),
    "dhcpSubClass": frozenset(),
    "dhcpTSigKey": frozenset(),
    "dhcpDnsZone": frozenset(),
    "dhcpFailOverPeer": frozenset(),
}

TYPE_BY_CLASS: dict[str, str] = {
    "dhcpservice": "dhcp_configuration",
    "dhcpsharednetwork": "dhcp_shared_network",
    "dhcpsubnet": "dhcp_subnet",
    "dhcppool": "dhcp_pool",
    "dhcpgroup": "dhcp_group",
    "dhcphost": "dhcp_host",
    "dhcpclass": "dhcp_class",
    "dhcpsubclass": "dhcp_subclass",
    "dhcptsigkey": "dhcp_tsig_key",
    "dhcpdnszone": "dhcp_dns_zone",
    "dhcpfailoverpeer": "dhcp_failover_peer",
}

CLASS_BY_TYPE: dict[str, str] = {
    "dhcp_configuration": "dhcpService",
    "dhcp_shared_network": "dhcpSharedNetwork",
    "dhcp_subnet": "dhcpSubnet",
    "dhcp_pool": "dhcpPool",
    "dhcp_group": "dhcpGroup",
    "dhcp_host": "dhcpHost",
    "dhcp_class": "dhcpClass",
    "dhcp_subclass": "dhcpSubClass",
    "dhcp_tsig_key": "dhcpTSigKey",
    "dhcp_dns_zone": "dhcpDnsZone",
    "dhcp_failover_peer": "dhcpFailOverPeer",
}


def find_dhcp_class(entry: Entry) -> str | None:
    """Identify the structural DHCP objectClass on an entry."""
    for oc in CLASS_BY_TYPE.values():
        if entry.has_object_class(oc):
            return oc
    return None


def validate_ipv4(address: str) -> str | None:
    """Check if address is a valid IPv4 address; returns error or None."""
    if not address or not address.strip():
        return _("This field is required.")
    try:
        ipaddress.IPv4Address(address.strip())
    except ValueError:
        return _("Invalid IPv4 address.")
    return None


def validate_mac(mac: str) -> str | None:
    """Check if mac matches 6 hex octet format; returns error or None."""
    if not mac or not mac.strip():
        return _("This field is required.")
    if MAC_RE.fullmatch(mac.strip()) is None:
        return _("Invalid MAC address.")
    return None


def validate_subnet_network(address: str, prefix_len: int) -> str | None:
    """Verify that address is the base network address for the given IPv4 prefix."""
    err = validate_ipv4(address)
    if err is not None:
        return err
    if not (0 <= prefix_len <= 32):
        return _("Prefix length must be between 0 and 32.")
    ip = ipaddress.IPv4Address(address.strip())
    net = ipaddress.IPv4Network(f"{address.strip()}/{prefix_len}", strict=False)
    if ip != net.network_address:
        msg = _("'{address}' is not a network address for /{prefix} (expected {expected}).")
        return msg.format(address=address, prefix=prefix_len, expected=net.network_address)
    return None


def validate_range(range_str: str, subnet: ipaddress.IPv4Network | None = None) -> str | None:
    """Check range syntax '<start> <end>' and subnet containment."""
    parts = range_str.strip().split()
    if len(parts) != 2:
        return _("Range must be '<start> <end>'.")
    try:
        start_ip = ipaddress.IPv4Address(parts[0])
    except ValueError:
        return _("Invalid start IPv4 address in range: '{ip}'.").format(ip=parts[0])
    try:
        end_ip = ipaddress.IPv4Address(parts[1])
    except ValueError:
        return _("Invalid end IPv4 address in range: '{ip}'.").format(ip=parts[1])
    if start_ip > end_ip:
        return _("Range start '{start}' is greater than end '{end}'.").format(
            start=parts[0], end=parts[1]
        )
    if subnet is not None and (start_ip not in subnet or end_ip not in subnet):
        return _("Range '{range}' is outside of subnet {subnet}.").format(
            range=range_str, subnet=str(subnet)
        )
    return None


def normalize_dhcp_options(options: Sequence[str]) -> list[str]:
    """Normalize DHCP option statements: remove 'option' prefix and quote domain-name."""
    result: list[str] = []
    for opt in options:
        item = opt.strip()
        if item.lower().startswith("option "):
            item = item[7:].strip()
        name, sep, rest = item.partition(" ")
        if name == "domain-name" and sep:
            val = rest.strip()
            if not (val.startswith('"') and val.endswith('"')):
                item = f'domain-name "{val}"'
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Statements and options rendered into a DHCP server configuration
# ---------------------------------------------------------------------------
#
# A DHCP daemon reads these values as configuration text, so a value that is more than one
# plain statement (``on commit { execute(...); }``, ``include "..."``, a ``}`` closing the
# block) would run commands or read files on the server. Only the grammar below is
# accepted; anything else is refused. ``deploy/dev/dhcp/render.py`` repeats a coarser
# version of these rules as defence in depth: keep the two in step.

_DHCP_STRING = r'"[ !#-\[\]-~]*"'  # printable ASCII, no quote, no backslash
_DHCP_INT = r"[0-9]{1,10}"
_DHCP_IPV4 = r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}"
_DHCP_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,251}[A-Za-z0-9])?"
_DHCP_ADDR = rf"(?:{_DHCP_IPV4}|{_DHCP_HOST})"
_DHCP_WORD = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
_DHCP_BOOL = r"(?:on|off|true|false)"
_DHCP_HEX = r"[0-9A-Fa-f]{1,2}(?::[0-9A-Fa-f]{1,2})*"
_DHCP_WORDS = rf"{_DHCP_WORD}(?:\s*,\s*{_DHCP_WORD})*"

#: statement keyword -> regular expression the rest of the statement must match
_DHCP_STATEMENTS: dict[str, str] = {
    "authoritative": "",
    "not authoritative": "",
    "default-lease-time": _DHCP_INT,
    "min-lease-time": _DHCP_INT,
    "max-lease-time": _DHCP_INT,
    "dynamic-bootp-lease-length": _DHCP_INT,
    "min-secs": _DHCP_INT,
    "filename": _DHCP_STRING,
    "server-name": _DHCP_STRING,
    "ddns-domainname": _DHCP_STRING,
    "ddns-rev-domainname": _DHCP_STRING,
    "ddns-hostname": _DHCP_STRING,
    "next-server": _DHCP_ADDR,
    "server-identifier": _DHCP_ADDR,
    "fixed-address": rf"{_DHCP_ADDR}(?:\s*,\s*{_DHCP_ADDR})*",
    "ddns-update-style": r"(?:none|interim|standard|ad-hoc)",
    "ddns-updates": _DHCP_BOOL,
    "do-forward-updates": _DHCP_BOOL,
    "update-static-leases": _DHCP_BOOL,
    "ping-check": _DHCP_BOOL,
    "boot-unknown-clients": _DHCP_BOOL,
    "use-host-decl-names": _DHCP_BOOL,
    "one-lease-per-client": _DHCP_BOOL,
    "get-lease-hostnames": _DHCP_BOOL,
    "always-reply-rfc1048": _DHCP_BOOL,
    "always-broadcast": _DHCP_BOOL,
    "ignore-client-uids": _DHCP_BOOL,
    "allow": rf"(?:{_DHCP_WORDS}|members of {_DHCP_STRING})",
    "deny": rf"(?:{_DHCP_WORDS}|members of {_DHCP_STRING})",
    "ignore": _DHCP_WORDS,
}
_DHCP_STATEMENT_RES = {k: re.compile(v) for k, v in _DHCP_STATEMENTS.items()}
_DHCP_KEYWORDS_LONGEST_FIRST = sorted(_DHCP_STATEMENTS, key=len, reverse=True)

_DHCP_OPTION_ARG = rf"(?:{_DHCP_STRING}|{_DHCP_HEX}|{_DHCP_ADDR})"
_DHCP_OPTION_RE = re.compile(
    rf"(?:option\s+)?([a-z][a-z0-9-]{{0,63}})\s+{_DHCP_OPTION_ARG}(?:\s*,\s*{_DHCP_OPTION_ARG})*"
)
#: words that must never lead an option (they introduce declarations or run code)
_DHCP_FORBIDDEN_OPTION_NAMES = frozenset({"execute", "include", "on", "space", "code"})


def _dhcp_text_problem(text: str) -> str | None:
    if not text.isascii() or not text.isprintable():
        return _("Must be a single line of printable ASCII text.")
    if any(c in text for c in ";{}#\\"):
        return _("Must not contain ';', '{', '}', '#' or a backslash.")
    return None


def validate_dhcp_statement(value: str) -> str | None:
    """Problem with a ``dhcpStatements`` value, or ``None`` when it is an accepted statement."""
    text = value.strip()
    problem = _dhcp_text_problem(text)
    if problem is not None:
        return problem
    for keyword in _DHCP_KEYWORDS_LONGEST_FIRST:
        if text.startswith(keyword):
            rest = text[len(keyword) :]
            if (rest == "" or rest[0].isspace()) and _DHCP_STATEMENT_RES[keyword].fullmatch(
                rest.strip()
            ):
                return None
    return _("Not an accepted DHCP statement (for example 'default-lease-time 600').")


def validate_dhcp_option(value: str) -> str | None:
    """Problem with a ``dhcpOption`` value, or ``None`` when it is an accepted option."""
    text = value.strip()
    problem = _dhcp_text_problem(text)
    if problem is not None:
        return problem
    match = _DHCP_OPTION_RE.fullmatch(text)
    if match is None or match.group(1) in _DHCP_FORBIDDEN_OPTION_NAMES:
        return _("Not an accepted DHCP option (for example 'routers 10.0.0.1').")
    return None
