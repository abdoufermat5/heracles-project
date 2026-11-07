"""Tests for the IPAM plugin (VLAN, Subnet, CIDR attribute, next_free_ip)."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.ipam as ipam
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.legacy import OC

BASE = "dc=test"
PARIS = f"ou=paris,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"domain"], "dc": [b"test"]})
    d.add(
        PARIS,
        {
            "objectClass": [b"top", b"organizationalUnit", OC.DEPARTMENT.encode()],
            "ou": [b"paris"],
        },
    )
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            "fdIpamVlan",
            "fdIpamSubnet",
            "ipHost",
        ]
    )
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    status = reg.register_plugin(
        ipam.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return reg


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def test_ipam_plugin_schema_requirement() -> None:
    reg = TypeRegistry()
    register_builtin_types(reg)
    # Without the schema classes, the plugin should report disabled
    status = reg.register_plugin(ipam.plugin(), {"inetorgperson", "posixaccount"})
    assert not status.enabled
    assert "fdIpamVlan" in status.missing_object_classes or "fdipamvlan" in [
        c.lower() for c in status.missing_object_classes
    ]


def test_vlan_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    values: dict[str, Any] = {
        "cn": "vlan100",
        "description": "Production VLAN",
        "fdIpamActive": True,
        "fdIpamVlanInnerId": 100,
        "fdIpamVlanQinQId": 10,
        "o": "Acme Corp",
    }
    dn = service.create("ipamVlan", PARIS, {"main": {"values": values}})
    assert dn == f"cn=vlan100,ou=ipam,{PARIS}"

    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("cn") == "vlan100"
    assert entry.text("description") == "Production VLAN"
    assert entry.text("fdIpamVlanInnerId") == "100"
    assert entry.text("fdIpamVlanQinQId") == "10"
    assert entry.text("fdIpamActive") == "TRUE"

    loaded = service.load("ipamVlan", dn)
    assert loaded.tabs["main"].values["fdIpamVlanInnerId"] == 100

    # Update
    service.update("ipamVlan", dn, {"main": {"values": {"description": "Updated VLAN"}}})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("description") == "Updated VLAN"

    # Delete
    service.delete("ipamVlan", dn)
    assert directory.get(dn) is None


def test_vlan_validation(service: ObjectService) -> None:
    # Invalid VLAN ID (> 4094)
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "ipamVlan",
            PARIS,
            {"main": {"values": {"cn": "invalid-vlan", "fdIpamVlanInnerId": 5000}}},
        )
    assert "main.fdIpamVlanInnerId" in exc_info.value.fields

    # Invalid VLAN ID (< 1)
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "ipamVlan",
            PARIS,
            {"main": {"values": {"cn": "invalid-vlan", "fdIpamVlanInnerId": 0}}},
        )
    assert "main.fdIpamVlanInnerId" in exc_info.value.fields


def test_subnet_crud_and_vlan_reference(service: ObjectService, directory: MemoryDirectory) -> None:
    # Create VLAN first
    vlan_dn = service.create(
        "ipamVlan",
        PARIS,
        {"main": {"values": {"cn": "vlan20", "fdIpamVlanInnerId": 20}}},
    )

    # Create Subnet referencing the VLAN
    subnet_values: dict[str, Any] = {
        "cn": "servers-net",
        "fdIpamSubnetCIDR": "10.100.0.0/24",
        "description": "Server Subnet",
        "fdIpamVlanDN": vlan_dn,
        "fdIpamActive": True,
        "fdIpamType": "IPv4",
    }
    subnet_dn = service.create("ipamSubnet", PARIS, {"main": {"values": subnet_values}})
    assert subnet_dn == f"cn=servers-net,ou=ipam,{PARIS}"

    entry = directory.get(subnet_dn)
    assert entry is not None
    assert entry.text("cn") == "servers-net"
    assert entry.text("fdIpamSubnetCIDR") == "10.100.0.0/24"
    assert entry.text("fdIpamVlanDN") == vlan_dn

    loaded = service.load("ipamSubnet", subnet_dn)
    assert loaded.tabs["main"].values["fdIpamSubnetCIDR"] == "10.100.0.0/24"
    assert loaded.tabs["main"].values["fdIpamVlanDN"] == vlan_dn

    # Delete subnet
    service.delete("ipamSubnet", subnet_dn)
    assert directory.get(subnet_dn) is None


def test_subnet_cidr_validation(service: ObjectService) -> None:
    # Invalid CIDR string
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "ipamSubnet",
            PARIS,
            {"main": {"values": {"cn": "bad-subnet", "fdIpamSubnetCIDR": "not-a-cidr"}}},
        )
    assert "main.fdIpamSubnetCIDR" in exc_info.value.fields

    # Valid IPv6 CIDR succeeds
    dn = service.create(
        "ipamSubnet",
        PARIS,
        {"main": {"values": {"cn": "v6-subnet", "fdIpamSubnetCIDR": "2001:db8::/64"}}},
    )
    assert "cn=v6-subnet" in dn


def test_next_free_ip_pure() -> None:
    cidr = "192.168.10.0/29"  # hosts: .1 to .6 (.0 is network, .7 is broadcast)
    used = {"192.168.10.1", "192.168.10.2"}

    # Next free should be .3
    assert ipam.next_free_ip(cidr, used) == "192.168.10.3"

    # Use .3, .4, .5
    used.update(["192.168.10.3", "192.168.10.4", "192.168.10.5"])
    assert ipam.next_free_ip(cidr, used) == "192.168.10.6"

    # Use all
    used.add("192.168.10.6")
    assert ipam.next_free_ip(cidr, used) is None


def test_next_free_ip_with_directory(directory: MemoryDirectory) -> None:
    # Add an entry with objectClass=ipHost and ipHostNumber=10.0.0.1
    host_dn = f"cn=srv1,{PARIS}"
    directory.add(
        host_dn,
        {
            "objectClass": [b"top", b"device", b"ipHost"],
            "cn": [b"srv1"],
            "ipHostNumber": [b"10.0.0.1", b"10.0.0.2"],
        },
    )

    # Next free in 10.0.0.0/24 checking directory directly
    free_ip = ipam.next_free_ip("10.0.0.0/24", directory)
    assert free_ip == "10.0.0.3"


def test_next_free_ip_ipv6() -> None:
    cidr = "2001:db8:1::/126"  # hosts: 2001:db8:1::1, 2001:db8:1::2, 2001:db8:1::3
    used = ["2001:db8:1::1"]
    assert ipam.next_free_ip(cidr, used) == "2001:db8:1::2"
