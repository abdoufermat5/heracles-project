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
