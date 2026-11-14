"""Tests for RADIUS plugin: user and group radiusprofile tabs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import heracles_plugins.radius as radius
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(GROUPS, {"objectClass": [b"organizationalUnit"], "ou": [b"groups"]})
    d.add(
        f"uid=user1,{PEOPLE}",
        {
            "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
            "uid": [b"user1"],
            "sn": [b"User"],
            "cn": [b"User One"],
        },
    )
    d.set_schema_object_classes(d.schema_object_classes() | {"radiusprofile"})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    status = registry.register_plugin(radius.plugin(), classes)
    assert status.enabled
    return ObjectService(directory, registry)


def create_user(service: ObjectService, tabs: dict[str, Any]) -> str:
    main: dict[str, Any] = {"main": {"values": {"uid": "jdoe", "givenName": "Jane", "sn": "Doe"}}}
    return service.create("user", BASE, {**main, **tabs})


def create_group(service: ObjectService, tabs: dict[str, Any], member: str | None = None) -> str:
    m = member or f"uid=user1,{PEOPLE}"
    main: dict[str, Any] = {
        "main": {"values": {"cn": "radius-users", "description": "RADIUS Group", "member": [m]}}
    }
    return service.create("group", BASE, {**main, **tabs})


def stored_entry(directory: MemoryDirectory, dn: str) -> Entry:
    entry = directory.get(dn)
    assert entry is not None
    return entry


# ------------------------------------------------------------- schema and ACLs


def test_tab_schema_requirement() -> None:
    d = MemoryDirectory(BASE)
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in d.schema_object_classes()}
    status = registry.register_plugin(radius.plugin(), classes)
    assert status.enabled
    assert registry.get("user").tab("radius") is None
    assert registry.get("group").tab("radius") is None

    # When radiusprofile is available, tabs are attached
    registry2 = TypeRegistry()
    register_builtin_types(registry2)
    status2 = registry2.register_plugin(radius.plugin(), classes | {"radiusprofile"})
    assert status2.enabled
    assert registry2.get("user").tab("radius") is not None
    assert registry2.get("group").tab("radius") is not None


def test_tab_acl_keys(service: ObjectService) -> None:
    user_type = service.registry.get("user")
    u_tab = user_type.tab("radius")
    assert u_tab is not None
    assert u_tab.acl_key == "radiusAccount"
    assert user_type.acl_object(u_tab) == "user/radiusAccount"

    group_type = service.registry.get("group")
    g_tab = group_type.tab("radius")
    assert g_tab is not None
    assert g_tab.acl_key == "radiusGroup"
    assert group_type.acl_object(g_tab) == "ogroup/radiusGroup"


# ------------------------------------------------------------------- user tests


def test_create_and_load_user_with_radius(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group_dn = create_group(service, {})
    dn = create_user(
        service,
        {
            "radius": {
                "active": True,
                "values": {
                    "radiusFramedProtocol": "PPP",
                    "radiusFramedIPAddress": "10.0.0.50",
                    "radiusFramedIPNetmask": "255.255.255.0",
                    "radiusFramedMTU": 1500,
                    "radiusFramedCompression": "Van-Jacobsen-TCP-IP",
                    "radiusServiceType": "Framed-User",
                    "radiusSessionTimeout": 3600,
                    "radiusIdleTimeout": 600,
                    "radiusPortLimit": 1,
                    "radiusExpiration": "2028-12-31",
                    "radiusTunnelMediumType": "IPv4",
                    "radiusTunnelType": "VLAN",
                    "radiusTunnelPrivateGroupId": "100",
                    "radiusGroupName": group_dn,
                    "radiusControlAttribute": "Auth-Type := Local",
                    "radiusReplyAttribute": "Reply-Message := 'Welcome'",
                    "radiusRequestAttribute": "NAS-Port-Type == Wireless-802.11",
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.has_object_class("radiusprofile")
    assert entry.text("radiusFramedProtocol") == "PPP"
    assert entry.text("radiusFramedIPAddress") == "10.0.0.50"
    assert entry.text("radiusFramedIPNetmask") == "255.255.255.0"
    assert entry.text("radiusFramedMTU") == "1500"
    assert entry.text("radiusSessionTimeout") == "3600"
    assert entry.text("radiusIdleTimeout") == "600"
    assert entry.text("radiusExpiration") == "20281231000000Z"
    assert entry.text("radiusGroupName") == group_dn
    assert entry.text("radiusControlAttribute") == "Auth-Type := Local"

    obj = service.load("user", dn)
    tab = obj.tabs["radius"]
    assert tab.active
    assert tab.values["radiusFramedProtocol"] == "PPP"
    assert tab.values["radiusFramedMTU"] == 1500
    assert tab.values["radiusExpiration"] == date(2028, 12, 31)
    assert tab.values["radiusGroupName"] == group_dn


def test_update_and_deactivate_user_radius(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = create_user(
        service,
        {
            "radius": {
                "active": True,
                "values": {
                    "radiusSessionTimeout": 1800,
                },
            }
        },
    )
    # Update
    service.update(
        "user",
        dn,
        {
            "radius": {
                "active": True,
                "values": {
                    "radiusSessionTimeout": 7200,
                    "radiusFramedIPAddress": "192.168.10.20",
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("radiusSessionTimeout") == "7200"
    assert entry.text("radiusFramedIPAddress") == "192.168.10.20"

    # Deactivate
    service.update("user", dn, {"radius": {"active": False, "values": {}}})
    entry = stored_entry(directory, dn)
    assert not entry.has_object_class("radiusprofile")
    assert entry.get("radiusSessionTimeout") == []
    assert entry.get("radiusFramedIPAddress") == []


# ------------------------------------------------------------------ group tests


def test_create_and_load_group_with_radius(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = create_group(
        service,
        {
            "radius": {
                "active": True,
                "values": {
                    "radiusTunnelMediumType": "IPv4",
                    "radiusTunnelType": "VLAN",
                    "radiusTunnelPrivateGroupId": "42",
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.has_object_class("radiusprofile")
    assert entry.text("radiusTunnelMediumType") == "IPv4"
    assert entry.text("radiusTunnelType") == "VLAN"
    assert entry.text("radiusTunnelPrivateGroupId") == "42"

    obj = service.load("group", dn)
    tab = obj.tabs["radius"]
    assert tab.active
    assert tab.values["radiusTunnelType"] == "VLAN"
    assert tab.values["radiusTunnelPrivateGroupId"] == "42"

    # Update group
    service.update(
        "group",
        dn,
        {
            "radius": {
                "active": True,
                "values": {
                    "radiusTunnelPrivateGroupId": "99",
                },
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("radiusTunnelPrivateGroupId") == "99"

    # Deactivate group
    service.update("group", dn, {"radius": {"active": False, "values": {}}})
    entry = stored_entry(directory, dn)
    assert not entry.has_object_class("radiusprofile")
    assert entry.get("radiusTunnelPrivateGroupId") == []
