"""Tests for the IPMI plugin (ipmiClient tab on server, workstation)."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.ipmi as ipmi
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.legacy import OC, PLUGIN_OBJECT_CLASSES

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
            *PLUGIN_OBJECT_CLASSES,
            "ipmiClient",
        ]
    )
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    classes = {c.lower() for c in directory.schema_object_classes()}
    reg.register_plugin(systems.plugin(), classes)
    status = reg.register_plugin(ipmi.plugin(), classes)
    assert status.enabled
    return reg


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def test_ipmi_on_server(service: ObjectService, directory: MemoryDirectory) -> None:
    srv_values: dict[str, Any] = {
        "cn": "srv-db",
        "description": "Database server",
    }
    ipmi_values: dict[str, Any] = {
        "fdIpmiIP": "192.168.100.50",
        "fdIpmiLogin": "ipmiadmin",
        "fdIpmiPassword": "secret_bmc_password",
    }
    tabs = {
        "main": {"values": srv_values},
        "ipmi": {"active": True, "values": ipmi_values},
    }
    dn = service.create("server", PARIS, tabs)

    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("ipmiClient")
    assert entry.text("fdIpmiIP") == "192.168.100.50"
    assert entry.text("fdIpmiLogin") == "ipmiadmin"
    # Password stored in cleartext for BMC protocol
    assert entry.text("fdIpmiPassword") == "secret_bmc_password"

    loaded = service.load("server", dn)
    assert loaded.tabs["ipmi"].active is True
    assert loaded.tabs["ipmi"].values["fdIpmiIP"] == "192.168.100.50"
    assert loaded.tabs["ipmi"].values["fdIpmiLogin"] == "ipmiadmin"
    # Password is write-only, so from_ldap gives None
    assert loaded.tabs["ipmi"].values["fdIpmiPassword"] is None

    # Update BMC IP
    service.update(
        "server",
        dn,
        {
            "ipmi": {
                "values": {
                    "fdIpmiIP": "192.168.100.51",
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("fdIpmiIP") == "192.168.100.51"
    # Existing password preserved
    assert entry.text("fdIpmiPassword") == "secret_bmc_password"

    # Deactivate ipmi tab
    service.update("server", dn, {"ipmi": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("ipmiClient")
    assert entry.get("fdIpmiIP") == []
    assert entry.get("fdIpmiPassword") == []


def test_ipmi_on_workstation(service: ObjectService, directory: MemoryDirectory) -> None:
    tabs = {
        "main": {"values": {"cn": "ws-lab"}},
        "ipmi": {
            "active": True,
            "values": {
                "fdIpmiIP": "10.0.5.10",
                "fdIpmiLogin": "root",
                "fdIpmiPassword": "calvin",
            },
        },
    }
    dn = service.create("workstation", PARIS, tabs)
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("fdIpmiIP") == "10.0.5.10"
    assert entry.text("fdIpmiPassword") == "calvin"
