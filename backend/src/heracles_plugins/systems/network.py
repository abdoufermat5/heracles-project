"""Network interfaces of a system: child entries and the copies on the system entry."""

from __future__ import annotations

from typing import Any, cast

from heracles.attributes import (
    BooleanAttr,
    CompositeAttr,
    ListAttr,
    ObjectRefAttr,
    StringAttr,
)
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles_plugins.systems.attrs import IpAttr, MacAttr

INTERFACE_CLASS = "hrcNetworkInterface"
IP_HOST_CLASS = "ipHost"
INTERFACE_FILTER = f"(objectClass={INTERFACE_CLASS})"
ATTR = "networkInterfaces"

FIELD_NAME = "cn"
FIELD_MAC = "macAddress"
FIELD_IPS = "ipHostNumber"
FIELD_VLAN = "hrcNetworkInterfaceVlanDN"
FIELD_TAGGED = "hrcNetworkInterfaceVlanTagged"
FIELD_SUBNET = "hrcNetworkInterfaceSubnetDN"


def interface_attribute() -> ListAttr[dict[str, Any]]:
    """The virtual ``networkInterfaces`` attribute (a list of interface records)."""
    item = CompositeAttr(
        "interface",
        _("Network interface"),
        [
            StringAttr(
                FIELD_NAME,
                _("Interface name"),
                description=_("For example eth0"),
                required=True,
                pattern=r"[A-Za-z0-9][A-Za-z0-9_.:@-]*",
                max_length=64,
            ),
            MacAttr(FIELD_MAC, _("MAC address"), description=_("Format aa:bb:cc:dd:ee:ff")),
            ListAttr(FIELD_IPS, _("IP addresses"), IpAttr("ip", _("IP address"))),
            ObjectRefAttr(FIELD_VLAN, _("VLAN"), ref_type="vlan"),
            BooleanAttr(FIELD_TAGGED, _("Tagged VLAN")),
            ObjectRefAttr(FIELD_SUBNET, _("Subnet"), ref_type="subnet"),
        ],
    )
    attr = ListAttr(
        ATTR,
        _("Network interfaces"),
        item,
        description=_("Interfaces of the system; their MAC and IP addresses are also kept on it"),
    )
    attr.stored = False
    return attr


_FIELDS = cast("CompositeAttr", interface_attribute().item).fields
_EXTRA_FIELDS = tuple(f for f in _FIELDS if f.name != FIELD_NAME)


def _search(directory: DirectoryClient, base: str, flt: str, scope: Scope) -> list[Entry]:
    try:
        return list(directory.search(base, flt, scope))
    except NoSuchObjectError:
        return []


def children(directory: DirectoryClient, dn: str) -> list[Entry]:
    """Interface entries below the system ``dn``."""
    return _search(directory, dn, INTERFACE_FILTER, Scope.ONE)


def load_interfaces(directory: DirectoryClient, dn: str) -> list[dict[str, Any]] | None:
    """Interface records read from the child entries, sorted by name."""
    records = [
        {f.name: f.from_ldap(e.get(f.name)) for f in _FIELDS} for e in children(directory, dn)
    ]
    records.sort(key=lambda r: str(r.get(FIELD_NAME) or "").lower())
    return records or None


def interfaces_of(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Interface records held in a tab's values."""
    raw = values.get(ATTR)
    if not isinstance(raw, list):
        return []
    return [r for r in cast("list[object]", raw) if isinstance(r, dict)]  # pyright: ignore[reportUnknownVariableType]


def all_macs(interfaces: list[dict[str, Any]]) -> list[str]:
    """Distinct MAC addresses of the interfaces, in order."""
    return list(dict.fromkeys(str(i[FIELD_MAC]) for i in interfaces if i.get(FIELD_MAC)))


def all_ips(interfaces: list[dict[str, Any]]) -> list[str]:
    """Distinct IP addresses of the interfaces, in order."""
    out: list[str] = []
    for iface in interfaces:
        ips = iface.get(FIELD_IPS)
        if isinstance(ips, list):
            out.extend(str(ip) for ip in cast("list[object]", ips))
    return list(dict.fromkeys(out))


def in_system_duplicates(interfaces: list[dict[str, Any]]) -> str | None:
    """First duplicate name, MAC or IP among the interfaces of one system (as a message)."""
    names: set[str] = set()
    macs: set[str] = set()
    ips: set[str] = set()
    for iface in interfaces:
        name = str(iface.get(FIELD_NAME) or "")
        if name:
            if name.lower() in names:
                return _("Interface name used twice: {value}").format(value=name)
            names.add(name.lower())
        mac = iface.get(FIELD_MAC)
        if mac:
            if mac in macs:
                return _("MAC address used twice: {value}").format(value=mac)
            macs.add(str(mac))
        for ip in all_ips([iface]):
            if ip in ips:
                return _("IP address used twice: {value}").format(value=ip)
            ips.add(ip)
    return None


def taken_elsewhere(
    directory: DirectoryClient,
    object_class: str,
    attr: str,
    value: str,
    own_dn: str | None,
) -> bool:
    """True if another entry (not ``own_dn`` nor below it) of the class has ``attr=value``."""
    flt = f"(&(objectClass={object_class})({attr}={escape_filter_value(value)}))"
    for entry in _search(directory, directory.base_dn, flt, Scope.SUBTREE):
        if own_dn is not None and dnlib.is_descendant(entry.dn, own_dn):
            continue
        return True
    return False


# ------------------------------------------------------------------ writing


def _child_attrs(iface: dict[str, Any]) -> dict[str, list[bytes]]:
    attrs: dict[str, list[bytes]] = {}
    for field in _EXTRA_FIELDS:
        raw = field.to_ldap(iface.get(field.name))
        if raw:
            attrs[field.name] = raw
    return attrs


def sync_children(directory: DirectoryClient, dn: str, interfaces: list[dict[str, Any]]) -> None:
    """Create, update and delete the child entries so they match ``interfaces``."""
    existing = {(e.text(FIELD_NAME) or "").lower(): e for e in children(directory, dn)}
    wanted: dict[str, dict[str, Any]] = {}
    for iface in interfaces:
        name = str(iface.get(FIELD_NAME) or "")
        if name:
            wanted[name.lower()] = iface
    for key, iface in wanted.items():
        attrs = _child_attrs(iface)
        entry = existing.get(key)
        if entry is None:
            name = str(iface[FIELD_NAME])
            directory.add(
                f"{FIELD_NAME}={dnlib.escape_rdn_value(name)},{dn}",
                {
                    "objectClass": [INTERFACE_CLASS.encode()],
                    FIELD_NAME: [name.encode()],
                    **attrs,
                },
            )
            continue
        mods: list[Modification] = []
        for field in _EXTRA_FIELDS:
            new = attrs.get(field.name, [])
            old = entry.get(field.name)
            if sorted(new) == sorted(old):
                continue
            mods.append(
                Modification("replace", field.name, new)
                if new
                else Modification("delete", field.name)
            )
        if mods:
            directory.modify(entry.dn, mods)
    for key, entry in existing.items():
        if key not in wanted:
            directory.delete(entry.dn, recursive=True)


def _replace_values(entry: Entry, attr: str, wanted: list[str]) -> list[Modification]:
    current = {v.decode("utf-8", errors="replace").lower() for v in entry.get(attr)}
    if {w.lower() for w in wanted} == current:
        return []
    if wanted:
        return [Modification("replace", attr, [w.encode() for w in wanted])]
    return [Modification("delete", attr)]


def sync_copies(directory: DirectoryClient, dn: str, interfaces: list[dict[str, Any]]) -> None:
    """Keep ``macAddress`` / ``ipHostNumber`` and the ``ipHost`` class of the system in step."""
    entry = directory.get(dn)
    if entry is None:
        return
    macs = all_macs(interfaces)
    ips = all_ips(interfaces)
    has_class = entry.has_object_class(IP_HOST_CLASS)
    mods: list[Modification] = []
    if ips and not has_class:
        mods.append(Modification("add", "objectClass", [IP_HOST_CLASS.encode()]))
    mods.extend(_replace_values(entry, FIELD_MAC, macs))
    mods.extend(_replace_values(entry, FIELD_IPS, ips))
    if not ips and has_class:
        mods.append(Modification("delete", "objectClass", [IP_HOST_CLASS.encode()]))
    if mods:
        directory.modify(dn, mods)
