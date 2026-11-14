"""Systems plugin: servers, workstations, terminals, printers, network devices, phones.

Every system is an entry below ``ou=systems`` of a department. Its network
interfaces are child entries (``cn=<interface>,<system dn>``); the MAC and IP
addresses of all interfaces are also copied on the system entry, which carries
the auxiliary class ``ipHost`` as soon as it has an IP address.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from heracles.attributes import (
    DepartmentAttr,
    ListAttr,
    ObjectRefAttr,
    PhoneAttr,
    StringAttr,
    TextAttr,
    UrlAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins.systems import network
from heracles_plugins.systems.attrs import (
    HostnameAttr,
    ImeiAttr,
    LockModeAttr,
    luhn_valid,
    normalize_ip,
    normalize_mac,
)

PLUGIN_NAME = "systems"
DEVICE_CLASS = "ieee802Device"
SYSTEM_CLASSES = (
    "hrcServer",
    "hrcWorkstation",
    "hrcTerminal",
    "hrcPrinter",
    "hrcPhone",
    "hrcMobilePhone",
)


@dataclass(slots=True)
class SystemsSettings:
    """Settings of the systems plugin."""

    #: Type names (``server``, ``workstation``...) that need at least one IP address.
    mandatory_ip_types: list[str] = field(default_factory=lambda: [])


def settings_of(ctx: TabContext) -> SystemsSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, SystemsSettings) else SystemsSettings()


# ----------------------------------------------------------------- base tab


class SystemTab(Tab):
    """Main tab shared by all system types: network interface handling."""

    name = "main"

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        ctx.values[network.ATTR] = (
            network.load_interfaces(ctx.directory, ctx.dn) if ctx.dn else None
        )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        if network.ATTR not in ctx.values:
            return
        interfaces = network.interfaces_of(ctx.values)
        for iface in interfaces:  # normalise whatever a caller put in the values
            mac = iface.get(network.FIELD_MAC)
            if isinstance(mac, str):
                iface[network.FIELD_MAC] = normalize_mac(mac) or mac
            ips = iface.get(network.FIELD_IPS)
            if isinstance(ips, list):
                iface[network.FIELD_IPS] = [
                    normalize_ip(str(ip)) or str(ip) for ip in cast("list[object]", ips)
                ]
        if ctx.creating or ctx.was_touched(network.ATTR):
            cls._check_interfaces(ctx, interfaces)
        if ctx.creating and not ctx.errors:
            ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))

    @classmethod
    def _check_interfaces(cls, ctx: TabContext, interfaces: list[dict[str, object]]) -> None:
        duplicate = network.in_system_duplicates(interfaces)
        if duplicate:
            ctx.error(network.ATTR, duplicate)
            return
        for mac in network.all_macs(interfaces):
            if network.taken_elsewhere(ctx.directory, DEVICE_CLASS, network.FIELD_MAC, mac, ctx.dn):
                ctx.error(network.ATTR, _("MAC address already in use: {value}").format(value=mac))
                return
        ips = network.all_ips(interfaces)
        for ip in ips:
            if network.taken_elsewhere(
                ctx.directory, network.IP_HOST_CLASS, network.FIELD_IPS, ip, ctx.dn
            ):
                ctx.error(network.ATTR, _("IP address already in use: {value}").format(value=ip))
                return
        if not ips and ctx.info.name in settings_of(ctx).mandatory_ip_types:
            ctx.error(network.ATTR, _("At least one IP address is required for this system."))

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        if ctx.dn is None or network.ATTR not in ctx.values:
            return
        interfaces = network.interfaces_of(ctx.values)
        network.sync_children(ctx.directory, ctx.dn, interfaces)
        network.sync_copies(ctx.directory, ctx.dn, interfaces)

    @classmethod
    def before_delete(cls, ctx: TabContext) -> None:
        if ctx.dn is None:
            return
        for entry in network.children(ctx.directory, ctx.dn):
            ctx.directory.delete(entry.dn, recursive=True)


def _identity() -> Section:
    return Section(
        _("Identity"),
        DepartmentAttr("base", _("Department")),
        HostnameAttr(
            "cn", _("Host name"), required=True, description=_("Name of the system (RFC 1123)")
        ),
        TextAttr("description", _("Description")),
    )


def _location() -> StringAttr:
    return StringAttr("l", _("Location"))


def _lock() -> LockModeAttr:
    return LockModeAttr(
        "hrcMode",
        _("Lock this system"),
        description=_("Prevents the system from being reinstalled"),
        default=False,
    )


def _network() -> Section:
    return Section(_("Network"), network.interface_attribute())


_LIST_ATTRS = ("cn", "description", "l")
_SEARCH_ATTRS = ("cn", "description", "l", "macAddress", "ipHostNumber")


# -------------------------------------------------------------------- types


class Server(ObjectType):
    name = "server"
    label = _("Server")
    label_plural = _("Servers")
    nav = "primary"
    nav_group = "infrastructure"
    icon = "server"
    category = "systems"
    filter = "(objectClass=hrcServer)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=servers,ou=systems"
    columns = _LIST_ATTRS
    search_attrs = _SEARCH_ATTRS

    class Main(SystemTab):
        label = _("Server")
        acl_key = "serverGeneric"
        object_classes = ("hrcServer", DEVICE_CLASS)
        identity = _identity()
        system = Section(_("System"), _location(), _lock())
        net = _network()


class Workstation(ObjectType):
    name = "workstation"
    label = _("Workstation")
    label_plural = _("Workstations")
    icon = "monitor"
    category = "systems"
    filter = "(objectClass=hrcWorkstation)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=workstations,ou=systems"
    columns = _LIST_ATTRS
    search_attrs = _SEARCH_ATTRS

    class Main(SystemTab):
        label = _("Workstation")
        acl_key = "workstationGeneric"
        object_classes = ("hrcWorkstation", DEVICE_CLASS)
        identity = _identity()
        system = Section(_("System"), _location(), _lock())
        net = _network()


class Terminal(ObjectType):
    name = "terminal"
    label = _("Terminal")
    label_plural = _("Terminals")
    icon = "terminal"
    category = "systems"
    filter = "(objectClass=hrcTerminal)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=terminals,ou=systems"
    columns = _LIST_ATTRS
    search_attrs = _SEARCH_ATTRS

    class Main(SystemTab):
        label = _("Terminal")
        acl_key = "terminalGeneric"
        object_classes = ("hrcTerminal", DEVICE_CLASS)
        identity = _identity()
        system = Section(_("System"), _location(), _lock())
        net = _network()


class Printer(ObjectType):
    name = "printer"
    label = _("Printer")
    label_plural = _("Printers")
    icon = "printer"
    category = "systems"
    filter = "(objectClass=hrcPrinter)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=printers,ou=systems"
    columns = _LIST_ATTRS
    search_attrs = _SEARCH_ATTRS

    class Main(SystemTab):
        label = _("Printer")
        acl_key = "printGeneric"
        object_classes = ("hrcPrinter", DEVICE_CLASS)
        identity = _identity()
        system = Section(
            _("Printer"),
            _location(),
            UrlAttr(
                "labeledURI",
                _("Printer URI"),
                description=_("For example ipp://print.example.org/printers/office"),
            ),
        )
        access = Section(
            _("Access"),
            ListAttr(
                "hrcPrinterUsers",
                _("Users allowed to print"),
                ObjectRefAttr("user", _("User or group"), ref_type="user"),
                description=_("Users or groups allowed to use the printer"),
            ),
            ListAttr(
                "hrcPrinterAdminUsers",
                _("Printer administrators"),
                ObjectRefAttr("admin", _("User or group"), ref_type="user"),
                description=_("Users or groups allowed to administer the printer"),
            ),
        )
        windows = Section(
            _("Print driver"),
            StringAttr("hrcPrinterWindowsInfFile", _("Print driver INF file")),
            StringAttr("hrcPrinterWindowsDriverDir", _("Print driver directory")),
            StringAttr("hrcPrinterWindowsDriverName", _("Print driver name")),
        )
        net = _network()


class NetworkDevice(ObjectType):
    name = "component"
    label = _("Network device")
    label_plural = _("Network devices")
    icon = "network"
    category = "systems"
    filter = (
        f"(&(objectClass=device)(objectClass={DEVICE_CLASS})"
        + "".join(f"(!(objectClass={c}))" for c in SYSTEM_CLASSES)
        + ")"
    )
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=netdevices,ou=systems"
    columns = ("cn", "description")
    search_attrs = ("cn", "description", "macAddress", "ipHostNumber")

    class Main(SystemTab):
        label = _("Network device")
        acl_key = "componentGeneric"
        object_classes = ("device", DEVICE_CLASS)
        identity = _identity()
        net = _network()


class Phone(ObjectType):
    name = "phone"
    label = _("Phone")
    label_plural = _("Phones")
    icon = "phone"
    category = "systems"
    filter = "(objectClass=hrcPhone)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=phones,ou=systems"
    columns = ("cn", "telephoneNumber", "description")
    search_attrs = ("cn", "description", "telephoneNumber", "serialNumber", "macAddress")

    class Main(SystemTab):
        label = _("Phone")
        acl_key = "phoneGeneric"
        object_classes = ("hrcPhone", DEVICE_CLASS)
        identity = _identity()
        system = Section(
            _("Phone"),
            StringAttr("serialNumber", _("Serial number")),
            PhoneAttr("telephoneNumber", _("Telephone number")),
        )
        net = _network()


class MobilePhone(ObjectType):
    name = "mobile_phone"
    acl_category = "mobilePhone"
    label = _("Mobile phone")
    label_plural = _("Mobile phones")
    icon = "smartphone"
    category = "systems"
    filter = "(objectClass=hrcMobilePhone)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=mobile,ou=systems"
    columns = ("cn", "telephoneNumber", "hrcMobileOS", "description")
    search_attrs = ("cn", "description", "telephoneNumber", "serialNumber", "hrcMobileIMEI")

    class Main(SystemTab):
        label = _("Mobile phone")
        acl_key = "mobilePhoneGeneric"
        object_classes = ("hrcMobilePhone", DEVICE_CLASS)
        identity = _identity()
        system = Section(
            _("Mobile phone"),
            StringAttr("serialNumber", _("Serial number")),
            ImeiAttr(
                "hrcMobileIMEI",
                _("IMEI"),
                description=_("15 digits, the last one being a Luhn check digit"),
            ),
            StringAttr("hrcMobileOS", _("Operating system")),
            PhoneAttr("telephoneNumber", _("Telephone number")),
            StringAttr("hrcMobilePUK", _("PUK code")),
        )
        net = _network()


TYPES = (Server, Workstation, Terminal, Printer, NetworkDevice, Phone, MobilePhone)


def plugin() -> Plugin:
    """Entry point of the systems plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=TYPES,
        required_object_classes=(DEVICE_CLASS, "device"),
        settings=SystemsSettings(),
    )


__all__ = [
    "TYPES",
    "MobilePhone",
    "NetworkDevice",
    "Phone",
    "Printer",
    "Server",
    "SystemTab",
    "SystemsSettings",
    "Terminal",
    "Workstation",
    "luhn_valid",
    "plugin",
]
