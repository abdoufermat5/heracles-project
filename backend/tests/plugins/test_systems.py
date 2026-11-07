"""Systems plugin: CRUD, network interfaces, validation, uniqueness, recursive delete."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.systems as systems
from heracles.ldap.client import Modification, Scope
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.systems.attrs import luhn_valid, normalize_ip, normalize_mac

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"
GOOD_IMEI = "490154203237518"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory, settings: Any = None) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        systems.plugin(),
        {c.lower() for c in directory.schema_object_classes()} | {"ieee802device", "device"},
    )
    assert status.enabled
    if settings is not None:
        registry.settings["systems"] = settings
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def iface(
    name: str, mac: str | None = None, ips: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    return {"cn": name, "macAddress": mac, "ipHostNumber": ips, **extra}


def create_server(
    service: ObjectService,
    cn: str = "web1",
    interfaces: list[dict[str, Any]] | None = None,
    **vals: Any,
) -> str:
    values: dict[str, Any] = {"cn": cn, **vals}
    if interfaces is not None:
        values["networkInterfaces"] = interfaces
    return service.create("server", BASE, {"main": {"values": values}})


def fields_of(service: ObjectService, type_name: str, values: dict[str, Any]) -> dict[str, str]:
    with pytest.raises(ObjectValidationError) as info:
        service.create(type_name, BASE, {"main": {"values": values}})
    return dict(info.value.fields)


# ---------------------------------------------------------------- CRUD

CASES = [
    ("server", "ou=servers,ou=systems", "fdServer", {"l": "Paris", "fdMode": True}),
    ("workstation", "ou=workstations,ou=systems", "fdWorkstation", {"l": "Lyon"}),
    ("terminal", "ou=terminals,ou=systems", "fdTerminal", {"l": "Lyon"}),
    (
        "printer",
        "ou=printers,ou=systems",
        "fdPrinter",
        {
            "labeledURI": "ipp://print.example.org/p1",
            "fdPrinterWindowsDriverName": "Generic",
            "fdPrinterUsers": ["uid=a,ou=people,dc=test"],
        },
    ),
    ("component", "ou=netdevices,ou=systems", "device", {"description": "switch"}),
    (
        "phone",
        "ou=phones,ou=systems",
        "fdPhone",
        {"serialNumber": "S1", "telephoneNumber": "+33 1 23 45"},
    ),
    (
        "mobile_phone",
        "ou=mobile,ou=systems",
        "fdMobilePhone",
        {"fdMobileIMEI": GOOD_IMEI, "fdMobileOS": "Android", "fdMobilePUK": "12345678"},
    ),
]


@pytest.mark.parametrize(("type_name", "rdn", "oc", "extra"), CASES)
def test_crud_each_type(
    directory: MemoryDirectory,
    service: ObjectService,
    type_name: str,
    rdn: str,
    oc: str,
    extra: dict[str, Any],
) -> None:
    if type_name == "printer":
        directory.add(
            "ou=people,dc=test", {"objectClass": [b"organizationalUnit"], "ou": [b"people"]}
        )
        directory.add("uid=a,ou=people,dc=test", {"objectClass": [b"inetOrgPerson"], "uid": [b"a"]})
    dn = service.create(
        type_name, BASE, {"main": {"values": {"cn": "host1", "description": "d", **extra}}}
    )
    assert dn == f"cn=host1,{rdn},{BASE}"
    entry = directory.get(dn)
    assert entry is not None
    assert {v.decode() for v in entry.get("objectClass")} == {oc, "ieee802Device"}
    state = service.load(type_name, dn)
    values = state.tabs["main"].values
    assert values["cn"] == "host1"
    for key, value in extra.items():
        assert values[key] == value
    service.update(type_name, dn, {"main": {"values": {"description": "changed"}}})
    assert service.load(type_name, dn).tabs["main"].values["description"] == "changed"
    listed = service.list(type_name, BASE)
    assert [r.dn for r in listed.items] == [dn]
    service.delete(type_name, dn)
    assert directory.get(dn) is None


def test_acl_keys(service: ObjectService) -> None:
    expected = {
        "server": "server/serverGeneric",
        "workstation": "workstation/workstationGeneric",
        "terminal": "terminal/terminalGeneric",
        "printer": "printer/printGeneric",
        "component": "component/componentGeneric",
        "phone": "phone/phoneGeneric",
        "mobile_phone": "mobilePhone/mobilePhoneGeneric",
    }
    for name, key in expected.items():
        info = service.registry.get(name)
        assert info.acl_object(info.main_tab) == key
        assert info.type.category == "systems"


def test_component_filter_excludes_other_systems(
    directory: MemoryDirectory, service: ObjectService
) -> None:
    srv = create_server(service, "srv")
    directory.modify(srv, [Modification("add", "objectClass", [b"device"])])
    service.create("component", BASE, {"main": {"values": {"cn": "sw1"}}})
    page = service.list(
        "component",
        BASE,
        scope=Scope.SUBTREE,
    )
    assert [r.values["cn"] for r in page.items] == ["sw1"]


def test_hostname_validation(service: ObjectService) -> None:
    for bad in ("-bad", "bad_name", "a..b", "x" * 64, "has space"):
        assert "main.cn" in fields_of(service, "server", {"cn": bad}), bad
    create_server(service, "ok-1.example.org")


def test_duplicate_name_rejected(service: ObjectService) -> None:
    create_server(service, "dup")
    assert "main.cn" in fields_of(service, "server", {"cn": "dup"})


# --------------------------------------------------------------- fdMode


def test_fdmode_encoding(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(service, "m1")
    entry = directory.get(dn)
    assert entry is not None and entry.texts("fdMode") == ["unlocked"]
    assert service.load("server", dn).tabs["main"].values["fdMode"] is False
    service.update("server", dn, {"main": {"values": {"fdMode": True}}})
    entry = directory.get(dn)
    assert entry is not None and entry.texts("fdMode") == ["locked"]
    assert service.load("server", dn).tabs["main"].values["fdMode"] is True
    # absent means unlocked
    directory.modify(
        dn,
        [Modification("delete", "fdMode")],
    )
    assert service.load("server", dn).tabs["main"].values["fdMode"] is False


# ------------------------------------------------------------ normalisers


def test_normalisers() -> None:
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("aabbccddeeff") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("aa:bb:cc:dd:ee") is None
    assert normalize_mac("aa:bb:cc:dd:ee:gg") is None
    assert normalize_ip(" 10.0.0.1 ") == "10.0.0.1"
    assert normalize_ip("2001:DB8:0:0::1") == "2001:db8::1"
    assert normalize_ip("10.0.0.256") is None
    assert luhn_valid(GOOD_IMEI)
    assert not luhn_valid("490154203237519")


# ------------------------------------------------------- interfaces & sync


def test_interfaces_sync_and_copies(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(
        service,
        interfaces=[
            iface(
                "eth0",
                "AA:BB:CC:00:00:01",
                ["10.0.0.5", "2001:db8::5"],
                fdNetworkInterfaceVlanTagged=True,
                fdNetworkInterfaceVlanDN="cn=v10,dc=test",
            ),
            iface("eth1", "aa-bb-cc-00-00-02"),
        ],
    )
    system = directory.get(dn)
    assert system is not None
    assert sorted(system.texts("macAddress")) == ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]
    assert sorted(system.texts("ipHostNumber")) == ["10.0.0.5", "2001:db8::5"]
    assert system.has_object_class("ipHost")
    eth0 = directory.get(f"cn=eth0,{dn}")
    assert eth0 is not None
    assert eth0.has_object_class("fdNetworkInterface")
    assert eth0.texts("macAddress") == ["aa:bb:cc:00:00:01"]
    assert eth0.texts("fdNetworkInterfaceVlanTagged") == ["TRUE"]
    assert eth0.texts("fdNetworkInterfaceVlanDN") == ["cn=v10,dc=test"]
    loaded = service.load("server", dn).tabs["main"].values["networkInterfaces"]
    assert [i["cn"] for i in loaded] == ["eth0", "eth1"]
    assert loaded[0]["ipHostNumber"] == ["10.0.0.5", "2001:db8::5"]

    # modify eth0, drop eth1, add eth2
    service.update(
        "server",
        dn,
        {
            "main": {
                "values": {
                    "networkInterfaces": [
                        iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.6"]),
                        iface("eth2", "aa:bb:cc:00:00:03", ["10.0.1.1"]),
                    ]
                }
            }
        },
    )
    assert directory.get(f"cn=eth1,{dn}") is None
    eth0 = directory.get(f"cn=eth0,{dn}")
    assert eth0 is not None and eth0.texts("ipHostNumber") == ["10.0.0.6"]
    assert eth0.get("fdNetworkInterfaceVlanTagged") == []
    system = directory.get(dn)
    assert system is not None
    assert sorted(system.texts("macAddress")) == ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:03"]
    assert sorted(system.texts("ipHostNumber")) == ["10.0.0.6", "10.0.1.1"]


def test_iphost_class_added_and_removed(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(service, interfaces=[iface("eth0", "aa:bb:cc:00:00:01")])
    system = directory.get(dn)
    assert system is not None and not system.has_object_class("ipHost")
    assert system.get("ipHostNumber") == []

    service.update(
        "server",
        dn,
        {
            "main": {
                "values": {"networkInterfaces": [iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.9"])]}
            }
        },
    )
    system = directory.get(dn)
    assert system is not None and system.has_object_class("ipHost")
    assert system.texts("ipHostNumber") == ["10.0.0.9"]

    service.update(
        "server",
        dn,
        {"main": {"values": {"networkInterfaces": [iface("eth0", "aa:bb:cc:00:00:01")]}}},
    )
    system = directory.get(dn)
    assert system is not None and not system.has_object_class("ipHost")
    assert system.get("ipHostNumber") == []
    assert system.texts("macAddress") == ["aa:bb:cc:00:00:01"]

    service.update("server", dn, {"main": {"values": {"networkInterfaces": []}}})
    system = directory.get(dn)
    assert system is not None and system.get("macAddress") == []
    assert directory.get(f"cn=eth0,{dn}") is None


def test_other_edit_keeps_interfaces(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(service, interfaces=[iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.5"])])
    service.update("server", dn, {"main": {"values": {"description": "x"}}})
    system = directory.get(dn)
    assert system is not None and system.texts("ipHostNumber") == ["10.0.0.5"]
    assert directory.get(f"cn=eth0,{dn}") is not None


# ----------------------------------------------------------- validation


def test_mac_and_ip_validation(service: ObjectService) -> None:
    f = fields_of(service, "server", {"cn": "a", "networkInterfaces": [iface("eth0", "zz:zz")]})
    assert "main.networkInterfaces" in f
    f = fields_of(
        service, "server", {"cn": "a", "networkInterfaces": [iface("eth0", None, ["300.1.1.1"])]}
    )
    assert "main.networkInterfaces" in f
    f = fields_of(service, "server", {"cn": "a", "networkInterfaces": [iface("bad name", None)]})
    assert "main.networkInterfaces" in f
    # an empty record is dropped
    dn = create_server(service, "blank", [{"cn": ""}])
    assert service.load("server", dn).tabs["main"].values["networkInterfaces"] is None


def test_in_system_duplicates(service: ObjectService) -> None:
    for ifaces in (
        [iface("eth0"), iface("ETH0")],
        [iface("eth0", "aa:bb:cc:00:00:01"), iface("eth1", "AA:BB:CC:00:00:01")],
        [iface("eth0", None, ["10.0.0.1"]), iface("eth1", None, ["10.0.0.1"])],
    ):
        assert "main.networkInterfaces" in fields_of(
            service, "server", {"cn": "a", "networkInterfaces": ifaces}
        )


def test_ip_uniqueness(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(service, "s1", [iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.5"])])
    f = fields_of(
        service,
        "workstation",
        {"cn": "w", "networkInterfaces": [iface("eth0", None, ["10.0.0.5"])]},
    )
    assert "main.networkInterfaces" in f
    # IPv6 compared in canonical form
    create_server(service, "s2", [iface("eth0", None, ["2001:DB8::1"])])
    f = fields_of(
        service, "terminal", {"cn": "t", "networkInterfaces": [iface("e", None, ["2001:db8:0::1"])]}
    )
    assert "main.networkInterfaces" in f
    # saving the owner again with its own address is fine
    service.update(
        "server",
        dn,
        {
            "main": {
                "values": {
                    "networkInterfaces": [
                        iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.5"]),
                        iface("eth1", None, ["10.0.0.6"]),
                    ]
                }
            }
        },
    )


def test_mac_uniqueness(service: ObjectService) -> None:
    create_server(service, "s1", [iface("eth0", "aa:bb:cc:00:00:01")])
    f = fields_of(
        service, "phone", {"cn": "p", "networkInterfaces": [iface("eth0", "AA:BB:CC:00:00:01")]}
    )
    assert "main.networkInterfaces" in f


def test_mandatory_ip_types(directory: MemoryDirectory) -> None:
    service = make_service(directory, systems.SystemsSettings(mandatory_ip_types=["server"]))
    assert "main.networkInterfaces" in fields_of(service, "server", {"cn": "a"})
    assert "main.networkInterfaces" in fields_of(
        service, "server", {"cn": "a", "networkInterfaces": [iface("eth0", "aa:bb:cc:00:00:01")]}
    )
    create_server(service, "a", [iface("eth0", None, ["10.1.1.1"])])
    service.create("workstation", BASE, {"main": {"values": {"cn": "w"}}})


def test_imei_validation(service: ObjectService) -> None:
    for bad in ("12345", "49015420323751", "490154203237519", "49015420323751a"):
        assert "main.fdMobileIMEI" in fields_of(
            service, "mobile_phone", {"cn": "m", "fdMobileIMEI": bad}
        ), bad
    dn = service.create(
        "mobile_phone", BASE, {"main": {"values": {"cn": "m", "fdMobileIMEI": "490154 2032-37518"}}}
    )
    assert service.load("mobile_phone", dn).tabs["main"].values["fdMobileIMEI"] == GOOD_IMEI


# --------------------------------------------------------------- delete


def test_recursive_delete(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(
        service,
        interfaces=[iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.5"]), iface("eth1", None)],
    )
    assert directory.get(f"cn=eth1,{dn}") is not None
    service.delete("server", dn)
    assert directory.get(dn) is None
    assert directory.get(f"cn=eth0,{dn}") is None
    assert directory.get(f"cn=eth1,{dn}") is None
    # the address is free again
    create_server(service, "again", [iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.5"])])


def test_rename_moves_interfaces(directory: MemoryDirectory, service: ObjectService) -> None:
    dn = create_server(service, "old", [iface("eth0", "aa:bb:cc:00:00:01", ["10.0.0.5"])])
    service.update("server", dn, {"main": {"values": {"cn": "new"}}})
    new_dn = f"cn=new,{SERVERS}"
    assert directory.get(f"cn=eth0,{new_dn}") is not None
    system = directory.get(new_dn)
    assert system is not None and system.texts("ipHostNumber") == ["10.0.0.5"]
