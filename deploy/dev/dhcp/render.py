#!/usr/bin/env python3
"""Render an ISC DHCP server configuration from the directory.

The DHCP module of Heracles stores its configuration in the standard DHCP LDAP
schema: one ``dhcpService`` entry whose subtree holds ``dhcpSubnet``,
``dhcpPool``, ``dhcpGroup``, ``dhcpSharedNetwork`` and ``dhcpHost`` entries,
each with ``dhcpStatements``, ``dhcpOption``, ``dhcpRange``, ``dhcpNetMask``
and ``dhcpHWAddress``.

    render-dhcpd-conf OUTPUT SUBNETS_JSON        # write the configuration
    render-dhcpd-conf --interface SUBNETS_JSON   # local interface to serve on

The interface mode prints the name of the local interface whose address is
inside one of the rendered subnets (the dev stack serves an isolated compose
network).
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

LDAP_URI = os.environ.get("LDAP_URI", "ldap://ldap:1389")
BASE_DN = os.environ.get("BASE_DN", "dc=heracles,dc=test")
ADMIN_DN = os.environ.get("LDAP_ADMIN_DN", f"cn=admin,{BASE_DN}")
ADMIN_PASSWORD = os.environ.get("LDAP_ADMIN_PASSWORD", "admin")
SERVICE_DN = os.environ.get("DHCP_SERVICE_DN", f"cn=dev-dhcp,ou=dhcp,{BASE_DN}")


@dataclass
class Entry:
    dn: str
    attrs: dict[str, list[str]] = field(default_factory=dict)

    def text(self, name: str) -> str | None:
        values = self.attrs.get(name.lower())
        return values[0] if values else None

    def values(self, name: str) -> list[str]:
        return self.attrs.get(name.lower(), [])

    def has_class(self, name: str) -> bool:
        return name.lower() in {c.lower() for c in self.values("objectClass")}


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith(" ") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def parse_ldif(text: str) -> list[Entry]:
    entries: list[Entry] = []
    current: Entry | None = None
    for line in _unfold(text):
        if line.lower().startswith("dn:"):
            current = Entry(dn=line.split(":", 1)[1].strip())
            entries.append(current)
            continue
        if current is None:
            continue
        if line.startswith("#"):
            continue
        name, _, rest = line.partition(":")
        value = rest[1:] if rest.startswith(":") else rest
        current.attrs.setdefault(name.strip().lower(), []).append(value.strip())
    return entries


def search() -> list[Entry]:
    result = subprocess.run(
        [
            "ldapsearch", "-x", "-LLL",
            "-H", LDAP_URI,
            "-D", ADMIN_DN,
            "-w", ADMIN_PASSWORD,
            "-b", SERVICE_DN,
            "(objectClass=*)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"directory search failed: {result.stderr.strip()}")
    return parse_ldif(result.stdout)


def _normalize(value: str) -> str:
    return " ".join(value.split())


def statements(entry: Entry, indent: str) -> list[str]:
    out = [f"{indent}{_normalize(s)};" for s in entry.values("dhcpStatements") if s.strip()]
    for option in entry.values("dhcpOption"):
        text = _normalize(option)
        if not text:
            continue
        if not text.startswith("option "):
            text = f"option {text}"
        out.append(f"{indent}{text};")
    return out


def ranges(entry: Entry, indent: str) -> list[str]:
    return [f"{indent}range {_normalize(r)};" for r in entry.values("dhcpRange") if r.strip()]


def host_block(entry: Entry, indent: str) -> list[str]:
    name = entry.text("cn") or "host"
    lines = [f'{indent}host {name.replace(" ", "-")} {{']
    hardware = entry.text("dhcpHWAddress")
    if hardware:
        parts = _normalize(hardware).split(" ", 1)
        if len(parts) == 2:
            lines.append(f"{indent}  hardware {parts[0]} {parts[1]};")
    body = statements(entry, indent + "  ")
    lines.extend(body)
    lines.append(f"{indent}}}")
    return lines


def group_block(entry: Entry, indent: str, entries: list[Entry]) -> list[str]:
    lines = [f"{indent}group {{"]
    lines.extend(statements(entry, indent + "  "))
    for child in _direct_children(entries, entry):
        if child.has_class("dhcpHost"):
            lines.extend(host_block(child, indent + "  "))
    lines.append(f"{indent}}}")
    return lines


def pool_block(entry: Entry, indent: str) -> list[str]:
    lines = [f"{indent}pool {{"]
    lines.extend(ranges(entry, indent + "  "))
    lines.extend(statements(entry, indent + "  "))
    lines.append(f"{indent}}}")
    return lines


def subnet_block(entry: Entry, indent: str, entries: list[Entry]) -> list[str]:
    network = entry.text("cn") or ""
    prefix = entry.text("dhcpNetMask")
    try:
        net = ipaddress.IPv4Network(f"{network}/{prefix}", strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        raise SystemExit(f"invalid subnet entry {entry.dn}: cn={network} dhcpNetMask={prefix}")
    lines = [f"{indent}subnet {net.network_address} netmask {net.netmask} {{"]
    lines.extend(ranges(entry, indent + "  "))
    lines.extend(statements(entry, indent + "  "))
    for child in _direct_children(entries, entry):
        if child.has_class("dhcpPool"):
            lines.extend(pool_block(child, indent + "  "))
        elif child.has_class("dhcpHost"):
            lines.extend(host_block(child, indent + "  "))
        elif child.has_class("dhcpGroup"):
            lines.extend(group_block(child, indent + "  ", entries))
    lines.append(f"{indent}}}")
    return lines


def _depth(dn: str) -> int:
    return dn.count(",")


def _direct_children(entries: list[Entry], parent: Entry) -> list[Entry]:
    """Entries whose RDN sits directly below ``parent``."""
    parent_dn = parent.dn.lower()
    return [
        e
        for e in entries
        if e.dn.lower().endswith("," + parent_dn) and _depth(e.dn) == _depth(parent.dn) + 1
    ]


def render(entries: list[Entry]) -> tuple[str, list[str]]:
    service = next((e for e in entries if e.has_class("dhcpService")), None)
    if service is None:
        raise SystemExit(f"no dhcpService entry under {SERVICE_DN}")
    lines = [
        "# Generated from the directory by render-dhcpd-conf; do not edit.",
        "ddns-update-style none;",
    ]
    lines.extend(statements(service, ""))
    subnets: list[str] = []
    for child in _direct_children(entries, service):
        if child.has_class("dhcpSubnet"):
            lines.extend(subnet_block(child, "", entries))
            prefix = child.text("dhcpNetMask")
            try:
                net = ipaddress.IPv4Network(f"{child.text('cn')}/{prefix}", strict=False)
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
                continue
            subnets.append(str(net))
        elif child.has_class("dhcpHost"):
            lines.extend(host_block(child, ""))
        elif child.has_class("dhcpGroup"):
            lines.extend(group_block(child, "", entries))
    return "\n".join(lines) + "\n", subnets


def local_addresses() -> dict[str, list[str]]:
    out = subprocess.run(
        ["ip", "-4", "-o", "addr", "show"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result: dict[str, list[str]] = {}
    for line in out.splitlines():
        parts = line.split()
        # 2: eth0    inet 192.168.220.2/24 brd ...
        if len(parts) < 4 or parts[2] != "inet":
            continue
        result.setdefault(parts[1], []).append(parts[3])
    return result


def serving_interface(subnets: list[str]) -> str:
    networks = [ipaddress.IPv4Network(s) for s in subnets]
    for interface, addresses in local_addresses().items():
        for address in addresses:
            iface = ipaddress.IPv4Interface(address)
            for network in networks:
                if iface.ip in network:
                    return interface
    raise SystemExit(f"no local interface is inside the configured subnets {subnets}")


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--interface":
        with open(argv[2], encoding="utf-8") as handle:
            subnets = json.load(handle)
        print(serving_interface(subnets))
        return 0
    if len(argv) == 3:
        config, subnets = render(search())
        with open(argv[1], "w", encoding="utf-8") as handle:
            handle.write(config)
        with open(argv[2], "w", encoding="utf-8") as handle:
            json.dump(subnets, handle)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
