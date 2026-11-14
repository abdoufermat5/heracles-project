"""Unit and integration tests for the Calendar plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.calendar_resources as calendar_resources
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
RESOURCES = f"ou=resources,{BASE}"

SOGO_CLASSES = {
    "inetOrgPerson",
    "organizationalPerson",
    "person",
    "hrcCalendarResource",
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
    status = registry.register_plugin(calendar_resources.plugin(), schema_classes)
    assert status.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_calendar_type_registration_and_acl(service: ObjectService) -> None:
    res_info = service.registry.get("calendar_resource")
    assert res_info is not None
    assert res_info.type.acl_category == "calendar_resources"
    assert res_info.main_tab.acl_key == "calendarResource"
    assert res_info.acl_object(res_info.main_tab) == "calendar_resources/calendarResource"
    assert res_info.main_tab.object_classes == ("inetOrgPerson", "hrcCalendarResource")
    assert res_info.type.rdn == "ou=resources"


def test_calendar_type_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["domain"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(calendar_resources.plugin(), schema_classes)

    assert "calendar_resource" not in [t.name for t in registry.list()]


def test_create_calendar_resource(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "calendar_resource",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "room-101",
                    "mail": "room101@example.com",
                    "description": "Conference room with 12 seats and projector",
                    "hrcResourceKind": "location",
                    "hrcResourceMultipleBookings": 0,
                }
            }
        },
    )
    assert dn == f"uid=room-101,{RESOURCES}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcCalendarResource" in entry.get("objectClass")
    assert b"inetOrgPerson" in entry.get("objectClass")
    assert entry.text("uid") == "room-101"
    assert entry.text("cn") == "room-101"
    assert entry.text("sn") == "room-101"
    assert entry.text("mail") == "room101@example.com"
    assert entry.text("description") == "Conference room with 12 seats and projector"
    assert entry.text("hrcResourceKind") == "location"
    assert entry.text("hrcResourceMultipleBookings") == "0"

    loaded = service.load("calendar_resource", dn)
    vals = loaded.tabs["main"].values
    assert vals["uid"] == "room-101"
    assert vals["mail"] == "room101@example.com"
    assert vals["description"] == "Conference room with 12 seats and projector"
    assert vals["hrcResourceKind"] == "location"
    assert vals["hrcResourceMultipleBookings"] == 0


def test_create_equipment_resource_with_multiple_bookings(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "calendar_resource",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "projector-pool",
                    "mail": "projectors@example.com",
                    "description": "Shared video projectors (5 available)",
                    "hrcResourceKind": "thing",
                    "hrcResourceMultipleBookings": 5,
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("hrcResourceKind") == "thing"
    assert entry.text("hrcResourceMultipleBookings") == "5"


def test_update_and_delete_calendar_resource(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "calendar_resource",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "room-202",
                    "description": "Small meeting room",
                    "hrcResourceKind": "location",
                }
            }
        },
    )

    # Update description and multiple bookings
    service.update(
        "calendar_resource",
        dn,
        {
            "main": {
                "values": {
                    "description": "Renovated executive boardroom",
                    "hrcResourceMultipleBookings": 2,
                }
            }
        },
    )
    loaded = service.load("calendar_resource", dn)
    assert loaded.tabs["main"].values["description"] == "Renovated executive boardroom"
    assert loaded.tabs["main"].values["hrcResourceMultipleBookings"] == 2

    # Listing
    listing = service.list("calendar_resource", BASE)
    assert dn in [item.dn for item in listing.items]

    # Delete
    service.delete("calendar_resource", dn)
    assert directory.get(dn) is None


def test_calendar_validation(service: ObjectService) -> None:
    # Missing required uid
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "calendar_resource",
            BASE,
            {"main": {"values": {"description": "Room without name"}}},
        )
    assert "uid" in str(exc_info.value)

    # Negative multiple bookings
    with pytest.raises(ObjectValidationError) as exc_info2:
        service.create(
            "calendar_resource",
            BASE,
            {"main": {"values": {"uid": "bad-room", "hrcResourceMultipleBookings": -1}}},
        )
    assert "hrcResourceMultipleBookings" in str(exc_info2.value)
