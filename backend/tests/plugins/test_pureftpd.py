"""Tests for Pure-FTPd plugin: status attribute, tab rules and storage."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.pureftpd as pureftpd
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.pureftpd import PureFtpdStatusAttr

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.set_schema_object_classes(d.schema_object_classes() | {"pureftpduser"})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    status = registry.register_plugin(pureftpd.plugin(), classes)
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


def test_pureftpd_status_attr_from_ldap() -> None:
    attr = PureFtpdStatusAttr("status", "Status")
    assert attr.from_ldap([]) is None
    assert attr.from_ldap([b"TRUE"]) is True
    assert attr.from_ldap([b"true"]) is True
    assert attr.from_ldap([b"1"]) is True
    assert attr.from_ldap([b"ENABLED"]) is True
    assert attr.from_ldap([b"enabled"]) is True

    assert attr.from_ldap([b"FALSE"]) is False
    assert attr.from_ldap([b"false"]) is False
    assert attr.from_ldap([b"0"]) is False
    assert attr.from_ldap([b"DISABLED"]) is False
    assert attr.from_ldap([b"disabled"]) is False


def test_pureftpd_status_attr_to_ldap() -> None:
    attr = PureFtpdStatusAttr("status", "Status")
    assert attr.to_ldap(None) == []
    assert attr.to_ldap(True) == [b"TRUE"]
    assert attr.to_ldap(False) == [b"FALSE"]


# ---------------------------------------------------------------- plugin tests


def test_tab_schema_requirement() -> None:
    d = MemoryDirectory(BASE)
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in d.schema_object_classes()}
    status = registry.register_plugin(pureftpd.plugin(), classes)
    assert status.enabled
    assert registry.get("user").tab("pureftpd") is None

    # When PureFTPdUser is present in schema, tab is attached
    registry2 = TypeRegistry()
    register_builtin_types(registry2)
    status2 = registry2.register_plugin(pureftpd.plugin(), classes | {"pureftpduser"})
    assert status2.enabled
    assert registry2.get("user").tab("pureftpd") is not None


def test_tab_acl_key(service: ObjectService) -> None:
    user_type = service.registry.get("user")
    tab = user_type.tab("pureftpd")
    assert tab is not None
    assert tab.acl_key == "pureftpdAccount"
    assert user_type.acl_object(tab) == "user/pureftpdAccount"


def test_create_user_with_pureftpd_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(
        service,
        {
            "pureftpd": {
                "active": True,
                "values": {
                    "FTPStatus": True,
                    "FTPUploadRatio": 2,
                    "FTPDownloadRatio": 1,
                    "FTPQuotaFiles": 1000,
                    "FTPQuotaMBytes": 500,
                    "FTPUploadBandwidth": 100,
                    "FTPDownloadBandwidth": 200,
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.has_object_class("PureFTPdUser")
    assert entry.text("FTPStatus") == "TRUE"
    assert entry.text("FTPUploadRatio") == "2"
    assert entry.text("FTPDownloadRatio") == "1"
    assert entry.text("FTPQuotaFiles") == "1000"
    assert entry.text("FTPQuotaMBytes") == "500"
    assert entry.text("FTPUploadBandwidth") == "100"
    assert entry.text("FTPDownloadBandwidth") == "200"

    obj = service.load("user", dn)
    tab = obj.tabs["pureftpd"]
    assert tab.active
    assert tab.values["FTPStatus"] is True
    assert tab.values["FTPUploadRatio"] == 2
    assert tab.values["FTPQuotaFiles"] == 1000


def test_update_user_pureftpd_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(
        service,
        {
            "pureftpd": {
                "active": True,
                "values": {
                    "FTPStatus": True,
                    "FTPUploadRatio": 1,
                },
            }
        },
    )
    service.update(
        "user",
        dn,
        {
            "pureftpd": {
                "active": True,
                "values": {
                    "FTPStatus": False,
                    "FTPUploadRatio": 5,
                    "FTPQuotaFiles": 200,
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("FTPStatus") == "FALSE"
    assert entry.text("FTPUploadRatio") == "5"
    assert entry.text("FTPQuotaFiles") == "200"


def test_deactivate_pureftpd_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(
        service,
        {
            "pureftpd": {
                "active": True,
                "values": {"FTPStatus": True, "FTPQuotaFiles": 50},
            }
        },
    )
    assert service.load("user", dn).tabs["pureftpd"].active
    service.update(
        "user",
        dn,
        {"pureftpd": {"active": False, "values": {}}},
    )
    entry = stored_entry(directory, dn)
    assert not entry.has_object_class("PureFTPdUser")
    assert entry.get("FTPStatus") == []
    assert entry.get("FTPQuotaFiles") == []


def test_invalid_negative_quota(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            {
                "pureftpd": {
                    "active": True,
                    "values": {"FTPQuotaFiles": -5},
                }
            },
        )
    assert "pureftpd.FTPQuotaFiles" in exc.value.fields
