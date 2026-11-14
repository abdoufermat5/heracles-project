"""Tests for File sharing plugin: quota attribute, tab rules and storage."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.file_sharing as file_sharing
from heracles.attributes import ValidationError
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.file_sharing import BytesSizeAttr

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.set_schema_object_classes(d.schema_object_classes() | {"hrcfilesharingaccount"})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    status = registry.register_plugin(file_sharing.plugin(), classes)
    assert status.enabled
    return ObjectService(directory, registry)


def create_user(service: ObjectService, tabs: dict[str, Any]) -> str:
    main: dict[str, Any] = {"main": {"values": {"uid": "jdoe", "givenName": "Jane", "sn": "Doe"}}}
    return service.create("user", BASE, {**main, **tabs})


def stored_entry(directory: MemoryDirectory, dn: str) -> Entry:
    entry = directory.get(dn)
    assert entry is not None
    return entry


# ------------------------------------------------------------- attribute tests


def test_bytes_size_attr_from_json() -> None:
    attr = BytesSizeAttr("quota", "Quota")
    assert attr.from_json(None) is None
    assert attr.from_json("") is None
    assert attr.from_json("10 GB") == "10 GB"
    assert attr.from_json("unlimited") == "unlimited"
    assert attr.from_json(1073741824) == "1073741824"
    assert attr.from_json(1024.0) == "1024"

    with pytest.raises(ValidationError):
        attr.from_json(1024.5)

    with pytest.raises(ValidationError):
        attr.from_json(-2)

    with pytest.raises(ValidationError):
        attr.from_json(["10 GB"])


def test_bytes_size_attr_validation() -> None:
    attr = BytesSizeAttr("quota", "Quota")
    for valid in ("10 GB", "500MB", "1024 B", "2 TB", "unlimited", "none", "default", "-1"):
        assert attr.validate(valid) == []

    for invalid in ("not a size", "10 XB", "MB", "size123"):
        assert len(attr.validate(invalid)) > 0


def test_bytes_size_attr_ldap_roundtrip() -> None:
    attr = BytesSizeAttr("quota", "Quota")
    assert attr.to_ldap(None) == []
    assert attr.to_ldap("10 GB") == [b"10 GB"]
    assert attr.from_ldap([b"10 GB"]) == "10 GB"
    assert attr.from_ldap([]) is None


# ---------------------------------------------------------------- plugin tests


def test_tab_schema_requirement(directory: MemoryDirectory) -> None:
    # When hrcFileSharingAccount is absent from schema, optional tab is dropped
    d = MemoryDirectory(BASE)
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in d.schema_object_classes()}
    status = registry.register_plugin(file_sharing.plugin(), classes)
    assert status.enabled
    assert registry.get("user").tab("file_sharing") is None

    # When hrcFileSharingAccount is present, tab is attached
    registry2 = TypeRegistry()
    register_builtin_types(registry2)
    status2 = registry2.register_plugin(file_sharing.plugin(), classes | {"hrcfilesharingaccount"})
    assert status2.enabled
    assert registry2.get("user").tab("file_sharing") is not None


def test_tab_acl_key(service: ObjectService) -> None:
    user_type = service.registry.get("user")
    tab = user_type.tab("file_sharing")
    assert tab is not None
    assert tab.acl_key == "fileSharingAccount"
    assert user_type.acl_object(tab) == "user/fileSharingAccount"


def test_create_user_with_file_sharing_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = create_user(
        service,
        {
            "file_sharing": {
                "active": True,
                "values": {
                    "hrcFileSharingQuota": "15 GB",
                    "hrcFileSharingHomeFolder": "/var/file_sharing/data/jdoe",
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.has_object_class("hrcFileSharingAccount")
    assert entry.text("hrcFileSharingQuota") == "15 GB"
    assert entry.text("hrcFileSharingHomeFolder") == "/var/file_sharing/data/jdoe"

    obj = service.load("user", dn)
    assert obj.tabs["file_sharing"].active
    assert obj.tabs["file_sharing"].values["hrcFileSharingQuota"] == "15 GB"
    assert (
        obj.tabs["file_sharing"].values["hrcFileSharingHomeFolder"] == "/var/file_sharing/data/jdoe"
    )


def test_update_user_file_sharing_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(
        service,
        {
            "file_sharing": {
                "active": True,
                "values": {"hrcFileSharingQuota": "10 GB"},
            }
        },
    )
    obj = service.load("user", dn)
    assert obj.tabs["file_sharing"].values["hrcFileSharingHomeFolder"] is None

    service.update(
        "user",
        dn,
        {
            "file_sharing": {
                "active": True,
                "values": {
                    "hrcFileSharingQuota": "50 GB",
                    "hrcFileSharingHomeFolder": "/home/jdoe/cloud",
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("hrcFileSharingQuota") == "50 GB"
    assert entry.text("hrcFileSharingHomeFolder") == "/home/jdoe/cloud"


def test_deactivate_file_sharing_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(
        service,
        {
            "file_sharing": {
                "active": True,
                "values": {"hrcFileSharingQuota": "10 GB"},
            }
        },
    )
    assert service.load("user", dn).tabs["file_sharing"].active
    service.update(
        "user",
        dn,
        {"file_sharing": {"active": False, "values": {}}},
    )
    entry = stored_entry(directory, dn)
    assert not entry.has_object_class("hrcFileSharingAccount")
    assert entry.get("hrcFileSharingQuota") == []


def test_create_user_with_invalid_quota(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            {
                "file_sharing": {
                    "active": True,
                    "values": {"hrcFileSharingQuota": "not-a-valid-size"},
                }
            },
        )
    assert "file_sharing.hrcFileSharingQuota" in exc.value.fields
