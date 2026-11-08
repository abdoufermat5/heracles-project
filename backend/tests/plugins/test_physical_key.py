"""Tests for the physical key plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.physical_key as pkey
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.physical_key import PhysicalKeySettings

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(d.schema_object_classes() | {"fdphysicalkey"})
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    p = pkey.plugin()
    status = registry.register_plugin(p, classes)
    assert status.enabled
    return ObjectService(directory, registry)


def test_schema_optional_tab_dropped() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    p = pkey.plugin()
    registry.register_plugin(p, {"inetorgperson"})
    info = registry.get("user")
    assert info.tab("physical_key") is None


def test_create_user_with_physical_key(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "physical_key": {
                "active": True,
                "values": {
                    "fdPhysicalKeyType": "mifare",
                    "fdPhysicalKeyValue": "04A1B2C3D4",
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("fdPhysicalKey")
    assert entry.text("fdPhysicalKeyType") == "mifare"
    assert entry.text("fdPhysicalKeyValue") == "04A1B2C3D4"


def test_default_key_type(service: ObjectService, directory: MemoryDirectory) -> None:
    service.registry.settings["physical_key"] = PhysicalKeySettings(default_type="fido2")
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "alice", "sn": "Smith", "givenName": "Alice"}},
            "physical_key": {
                "active": True,
                "values": {
                    "fdPhysicalKeyValue": "YUBI-12345",
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("fdPhysicalKeyType") == "fido2"
    assert entry.text("fdPhysicalKeyValue") == "YUBI-12345"


def test_update_physical_key(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "bob", "sn": "Builder", "givenName": "Bob"}},
            "physical_key": {
                "active": True,
                "values": {
                    "fdPhysicalKeyType": "rfid",
                    "fdPhysicalKeyValue": "1001",
                },
            },
        },
    )
    service.update(
        "user",
        dn,
        {
            "physical_key": {
                "values": {
                    "fdPhysicalKeyValue": "1002",
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("fdPhysicalKeyValue") == "1002"


def test_deactivate_physical_key_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "carol", "sn": "Carol", "givenName": "Carol"}},
            "physical_key": {
                "active": True,
                "values": {
                    "fdPhysicalKeyType": "hid",
                    "fdPhysicalKeyValue": "9999",
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("fdPhysicalKey")

    service.update("user", dn, {"physical_key": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("fdPhysicalKey")
    assert entry.first("fdPhysicalKeyType") is None
    assert entry.first("fdPhysicalKeyValue") is None
