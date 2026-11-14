"""Unit and integration tests for the Mail protection plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.mail_protection as mail_protection
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"

MAILINBLACK_CLASSES = {
    "inetOrgPerson",
    "organizationalPerson",
    "person",
    "hrcMailProtectionUser",
    "organizationalUnit",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=MAILINBLACK_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status = registry.register_plugin(mail_protection.plugin(), schema_classes)
    assert status.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_mail_protection_tab_registration_and_acl(service: ObjectService) -> None:
    user_info = service.registry.get("user")
    tab = user_info.tab("mail_protection")
    assert tab is not None
    assert tab.acl_key == "mailProtectionUser"
    assert user_info.acl_object(tab) == "user/mailProtectionUser"
    assert tab.optional is True
    assert tab.object_classes == ("hrcMailProtectionUser",)


def test_mail_protection_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["inetOrgPerson", "organizationalPerson", "person"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(mail_protection.plugin(), schema_classes)

    user_info = registry.get("user")
    assert user_info.tab("mail_protection") is None


def test_create_user_with_mail_protection(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "aliced", "sn": "Durand", "givenName": "Alice"}},
            "mail_protection": {
                "active": True,
                "values": {
                    "hrcMailProtectionProtect": True,
                },
            },
        },
    )
    assert dn == f"uid=aliced,{PEOPLE}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcMailProtectionUser" in entry.get("objectClass")
    assert entry.text("hrcMailProtectionProtect") == "TRUE"

    loaded = service.load("user", dn)
    assert loaded.tabs["mail_protection"].active is True
    assert loaded.tabs["mail_protection"].values["hrcMailProtectionProtect"] is True


def test_update_and_deactivate_mail_protection(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "bobm", "sn": "Martin", "givenName": "Bob"}},
            "mail_protection": {
                "active": True,
                "values": {
                    "hrcMailProtectionProtect": True,
                },
            },
        },
    )

    # Update to False
    service.update(
        "user",
        dn,
        {
            "mail_protection": {
                "values": {
                    "hrcMailProtectionProtect": False,
                }
            }
        },
    )
    loaded = service.load("user", dn)
    assert loaded.tabs["mail_protection"].values["hrcMailProtectionProtect"] is False
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("hrcMailProtectionProtect") == "FALSE"

    # Deactivate tab
    service.update("user", dn, {"mail_protection": {"active": False}})
    entry2 = directory.get(dn)
    assert entry2 is not None
    assert b"hrcMailProtectionUser" not in entry2.get("objectClass")
    assert entry2.get("hrcMailProtectionProtect") == []

    loaded_deactivated = service.load("user", dn)
    assert loaded_deactivated.tabs["mail_protection"].active is False
