"""Tests for Quota plugin: per-filesystem quota composite, user tab and server service."""

from __future__ import annotations

from typing import Any, cast

import pytest

import heracles_plugins.posix as posix
import heracles_plugins.quota as quota
import heracles_plugins.systems as systems
from heracles.attributes import ValidationError
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.quota import BlockLimitAttr, QuotaEntryAttr

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
SERVERS = f"ou=servers,ou=systems,{BASE}"
SYSTEMS = f"ou=systems,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(SYSTEMS, {"objectClass": [b"organizationalUnit"], "ou": [b"systems"]})
    d.add(SERVERS, {"objectClass": [b"organizationalUnit"], "ou": [b"servers"]})
    d.set_schema_object_classes(
        d.schema_object_classes()
        | {"systemquotas", "quotaservice", "fdserver", "device", "ieee802device"}
    )
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    for pl in (posix.plugin(), systems.plugin(), quota.plugin()):
        status = registry.register_plugin(pl, classes)
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


def test_block_limit_attr_from_json() -> None:
    attr = BlockLimitAttr("limit", "Limit")
    assert attr.from_json(None) is None
    assert attr.from_json("") is None
    assert attr.from_json(1000) == "1000"
    assert attr.from_json(5000.0) == "5000"
    assert attr.from_json("10 GB") == "10 GB"
    assert attr.from_json("-1") == "-1"

    with pytest.raises(ValidationError):
        attr.from_json(100.5)

    with pytest.raises(ValidationError):
        attr.from_json(-5)

    with pytest.raises(ValidationError):
        attr.from_json(["1000"])


def test_block_limit_attr_validation() -> None:
    attr = BlockLimitAttr("limit", "Limit")
    for valid in ("1000", "500 MB", "10 GB", "unlimited", "none", "-1", "4096k"):
        assert attr.validate(valid) == []

    for invalid in ("invalid", "100 XB", "some text"):
        assert len(attr.validate(invalid)) > 0


def test_quota_entry_composite() -> None:
    attr = QuotaEntryAttr()
    raw = [b"/dev/sda1:1000:2000:10:20:nas1"]
    parsed = attr.from_ldap(raw)
    assert parsed is not None
    assert parsed["quotaDevice"] == "/dev/sda1"
    assert parsed["quotaBlockSoftLimit"] == "1000"
    assert parsed["quotaBlockHardLimit"] == "2000"
    assert parsed["quotaInodeSoftLimit"] == 10
    assert parsed["quotaInodeHardLimit"] == 20
    assert parsed["quotaServer"] == "nas1"

    packed = attr.to_ldap(parsed)
    assert packed == [b"/dev/sda1:1000:2000:10:20:nas1"]


# ------------------------------------------------------------ user quota tests


def test_quota_requires_posix(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            {
                "quota": {
                    "active": True,
                    "values": {
                        "quota": [
                            {
                                "quotaDevice": "/dev/sda1",
                                "quotaBlockSoftLimit": "1000",
                                "quotaBlockHardLimit": "2000",
                            }
                        ]
                    },
                }
            },
        )
    assert "quota" in exc.value.fields


def test_tab_acl_keys(service: ObjectService) -> None:
    user_type = service.registry.get("user")
    u_tab = user_type.tab("quota")
    assert u_tab is not None
    assert u_tab.acl_key == "quotaAccount"
    assert user_type.acl_object(u_tab) == "user/quotaAccount"

    server_type = service.registry.get("server")
    s_tab = server_type.tab("serviceQuota")
    assert s_tab is not None
    assert s_tab.acl_key == "serviceQuota"
    assert server_type.acl_object(s_tab) == "server/serviceQuota"


def test_create_and_load_user_with_quota(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = create_user(
        service,
        {
            "posix": {"active": True, "values": {}},
            "quota": {
                "active": True,
                "values": {
                    "quota": [
                        {
                            "quotaDevice": "/home",
                            "quotaBlockSoftLimit": "500000",
                            "quotaBlockHardLimit": "1000000",
                            "quotaInodeSoftLimit": 5000,
                            "quotaInodeHardLimit": 10000,
                            "quotaServer": "filer01",
                        },
                        {
                            "quotaDevice": "/var/mail",
                            "quotaBlockSoftLimit": "200000",
                            "quotaBlockHardLimit": "400000",
                            "quotaInodeSoftLimit": 1000,
                            "quotaInodeHardLimit": 2000,
                            "quotaServer": "mailsrv",
                        },
                    ]
                },
            },
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.has_object_class("systemQuotas")
    quotas = entry.texts("quota")
    assert len(quotas) == 2
    assert "/home:500000:1000000:5000:10000:filer01" in quotas
    assert "/var/mail:200000:400000:1000:2000:mailsrv" in quotas

    obj = service.load("user", dn)
    tab = obj.tabs["quota"]
    assert tab.active
    raw_items = tab.values["quota"]
    assert isinstance(raw_items, list)
    items = cast("list[dict[str, Any]]", raw_items)
    assert len(items) == 2
    first = items[0]
    assert isinstance(first, dict)
    assert first["quotaDevice"] == "/home"
    assert first["quotaBlockSoftLimit"] == "500000"
    assert first["quotaInodeSoftLimit"] == 5000


def test_update_and_deactivate_user_quota(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = create_user(
        service,
        {
            "posix": {"active": True, "values": {}},
            "quota": {
                "active": True,
                "values": {
                    "quota": [
                        {
                            "quotaDevice": "/home",
                            "quotaBlockSoftLimit": "1000",
                            "quotaBlockHardLimit": "2000",
                        }
                    ]
                },
            },
        },
    )
    # Update quota rule
    service.update(
        "user",
        dn,
        {
            "quota": {
                "active": True,
                "values": {
                    "quota": [
                        {
                            "quotaDevice": "/home",
                            "quotaBlockSoftLimit": "2000",
                            "quotaBlockHardLimit": "4000",
                        }
                    ]
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.texts("quota") == ["/home:2000:4000:::"]

    # Deactivate quota
    service.update("user", dn, {"quota": {"active": False, "values": {}}})
    entry = stored_entry(directory, dn)
    assert not entry.has_object_class("systemQuotas")
    assert entry.get("quota") == []


# ---------------------------------------------------------- server quota tests


def test_server_service_quota(service: ObjectService, directory: MemoryDirectory) -> None:
    server_dn = service.create(
        "server",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "srv-storage",
                    "description": "Storage Server",
                }
            },
            "serviceQuota": {
                "active": True,
                "values": {
                    "quotaDevice": "/dev/sdb1",
                    "quotaBlockSize": 4096,
                    "quotaDesc": "Primary storage pool",
                    "quotaMsgCharsetSupport": "UTF-8",
                    "quotaMailCommand": "/usr/bin/mail -s",
                    "quotaMsgFromSupport": "support@example.org",
                    "quotaMsgContactSupport": "admin@example.org",
                    "quotaCarbonCopyMail": "audit@example.org",
                    "quotaMsgSubjectSupport": "Disk quota exceeded warning",
                    "quotaMsgContentSupport": "You have exceeded your storage limit.",
                    "quotaMsgSignatureSupport": "-- IT Team",
                    "quotaLdapServer": "ldap://localhost:389",
                    "quotaLdapServerUserDn": "cn=admin,dc=test",
                    "quotaLdapServerUserPassword": "secretpassword",
                },
            },
        },
    )
    entry = stored_entry(directory, server_dn)
    assert entry.has_object_class("quotaService")
    assert entry.text("quotaDevice") == "/dev/sdb1"
    assert entry.text("quotaBlockSize") == "4096"
    assert entry.text("quotaDesc") == "Primary storage pool"
    assert entry.text("quotaMailCommand") == "/usr/bin/mail -s"
    assert entry.text("quotaLdapServerUserPassword") == "secretpassword"

    obj = service.load("server", server_dn)
    tab = obj.tabs["serviceQuota"]
    assert tab.active
    assert tab.values["quotaBlockSize"] == 4096
    assert tab.values["quotaMsgFromSupport"] == "support@example.org"

    # Update serviceQuota
    service.update(
        "server",
        server_dn,
        {
            "serviceQuota": {
                "active": True,
                "values": {
                    "quotaBlockSize": 8192,
                    "quotaDesc": "Updated storage pool",
                },
            }
        },
    )
    entry = stored_entry(directory, server_dn)
    assert entry.text("quotaBlockSize") == "8192"
    assert entry.text("quotaDesc") == "Updated storage pool"

    # Deactivate serviceQuota
    service.update("server", server_dn, {"serviceQuota": {"active": False, "values": {}}})
    entry = stored_entry(directory, server_dn)
    assert not entry.has_object_class("quotaService")
    assert entry.get("quotaDevice") == []
