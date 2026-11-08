"""Unit and integration tests for the SOGo plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.sogo as sogo
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
RESOURCES = f"ou=resources,{BASE}"

SOGO_CLASSES = {
    "inetOrgPerson",
    "organizationalPerson",
    "person",
    "CalendarResource",
    "organizationalUnit",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=SOGO_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status = registry.register_plugin(sogo.plugin(), schema_classes)
    assert status.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_sogo_type_registration_and_acl(service: ObjectService) -> None:
    res_info = service.registry.get("sogo_resource")
    assert res_info is not None
    assert res_info.type.acl_category == "sogo"
    assert res_info.main_tab.acl_key == "sogoResource"
    assert res_info.acl_object(res_info.main_tab) == "sogo/sogoResource"
    assert res_info.main_tab.object_classes == ("inetOrgPerson", "CalendarResource")
    assert res_info.type.rdn == "ou=resources"


def test_sogo_type_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["domain"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(sogo.plugin(), schema_classes)

    assert "sogo_resource" not in [t.name for t in registry.list()]


def test_create_sogo_resource(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "sogo_resource",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "room-101",
                    "mail": "room101@example.com",
                    "description": "Conference room with 12 seats and projector",
                    "Kind": "location",
                    "Multiplebookings": 0,
                }
            }
        },
    )
    assert dn == f"uid=room-101,{RESOURCES}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"CalendarResource" in entry.get("objectClass")
    assert b"inetOrgPerson" in entry.get("objectClass")
    assert entry.text("uid") == "room-101"
    assert entry.text("cn") == "room-101"
    assert entry.text("sn") == "room-101"
    assert entry.text("mail") == "room101@example.com"
    assert entry.text("description") == "Conference room with 12 seats and projector"
    assert entry.text("Kind") == "location"
    assert entry.text("Multiplebookings") == "0"

    loaded = service.load("sogo_resource", dn)
    vals = loaded.tabs["main"].values
    assert vals["uid"] == "room-101"
    assert vals["mail"] == "room101@example.com"
    assert vals["description"] == "Conference room with 12 seats and projector"
    assert vals["Kind"] == "location"
    assert vals["Multiplebookings"] == 0


def test_create_equipment_resource_with_multiple_bookings(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "sogo_resource",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "projector-pool",
                    "mail": "projectors@example.com",
                    "description": "Shared video projectors (5 available)",
                    "Kind": "thing",
                    "Multiplebookings": 5,
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("Kind") == "thing"
    assert entry.text("Multiplebookings") == "5"


def test_update_and_delete_sogo_resource(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "sogo_resource",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "room-202",
                    "description": "Small meeting room",
                    "Kind": "location",
                }
            }
        },
    )

    # Update description and multiple bookings
    service.update(
        "sogo_resource",
        dn,
        {
            "main": {
                "values": {
                    "description": "Renovated executive boardroom",
                    "Multiplebookings": 2,
                }
            }
        },
    )
    loaded = service.load("sogo_resource", dn)
    assert loaded.tabs["main"].values["description"] == "Renovated executive boardroom"
    assert loaded.tabs["main"].values["Multiplebookings"] == 2

    # Listing
    listing = service.list("sogo_resource", BASE)
    assert dn in [item.dn for item in listing.items]

    # Delete
    service.delete("sogo_resource", dn)
    assert directory.get(dn) is None


def test_sogo_validation(service: ObjectService) -> None:
    # Missing required uid
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "sogo_resource",
            BASE,
            {"main": {"values": {"description": "Room without name"}}},
        )
    assert "uid" in str(exc_info.value)

    # Negative multiple bookings
    with pytest.raises(ObjectValidationError) as exc_info2:
        service.create(
            "sogo_resource",
            BASE,
            {"main": {"values": {"uid": "bad-room", "Multiplebookings": -1}}},
        )
    assert "Multiplebookings" in str(exc_info2.value)
