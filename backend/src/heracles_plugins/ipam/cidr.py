"""CIDR attribute and IP address allocation utilities for IPAM."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from typing import Any

from heracles.attributes import StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, Scope


class CidrAttr(StringAttr):
    """An IPv4 or IPv6 CIDR network notation (e.g. ``192.168.1.0/24``)."""

    kind = "cidr"

    def __init__(self, name: str, label: str, *, strict: bool = False, **kwargs: Any) -> None:
        super().__init__(name, label, **kwargs)
        self.strict = strict

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        val = value.strip()
        try:
            ipaddress.ip_network(val, strict=self.strict)
        except ValueError:
            errors.append(_("Invalid CIDR notation (e.g. 192.168.1.0/24 or 2001:db8::/64)."))
        return errors

    def to_ldap(self, value: str | None) -> list[bytes]:
        if value is None or not value.strip():
            return []
        try:
            net = ipaddress.ip_network(value.strip(), strict=False)
            return [str(net).encode("utf-8")]
        except ValueError:
            return [value.strip().encode("utf-8")]


def find_used_ips(directory: DirectoryClient, base: str | None = None) -> set[str]:
    """Return all ``ipHostNumber`` values currently in the directory ((objectClass=ipHost))."""
    root = base or directory.base_dn
    entries = directory.search(root, "(objectClass=ipHost)", Scope.SUBTREE, attrs=["ipHostNumber"])
    used: set[str] = set()
    for entry in entries:
        for ip in entry.texts("ipHostNumber"):
            try:
                used.add(str(ipaddress.ip_address(ip.strip())))
            except ValueError:
                used.add(ip.strip())
    return used


def next_free_ip(
    subnet_cidr: str | ipaddress.IPv4Network | ipaddress.IPv6Network,
    used_ips: Iterable[str | ipaddress.IPv4Address | ipaddress.IPv6Address] | DirectoryClient,
) -> str | None:
    """Return the next available IP address in ``subnet_cidr`` that is not in ``used_ips``.

    If ``used_ips`` is a :class:`DirectoryClient`, all ``ipHostNumber`` entries in the
    directory are searched.
    """
    if isinstance(used_ips, DirectoryClient):
        used_set = find_used_ips(used_ips)
    else:
        used_set: set[str] = set()
        for ip in used_ips:
            if isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
                used_set.add(str(ip))
            else:
                s = str(ip).strip()
                try:
                    used_set.add(str(ipaddress.ip_address(s)))
                except ValueError:
                    used_set.add(s)

    net = (
        subnet_cidr
        if isinstance(subnet_cidr, (ipaddress.IPv4Network, ipaddress.IPv6Network))
        else ipaddress.ip_network(str(subnet_cidr).strip(), strict=False)
    )

    for host in net.hosts():
        canonical = str(host)
        if canonical not in used_set:
            return canonical

    return None
