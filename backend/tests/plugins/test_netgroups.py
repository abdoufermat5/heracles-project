"""Tests for the Netgroup plugin (nisNetgroup type and user/system membership tabs)."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.netgroups as netgroups
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.names import OC, PLUGIN_OBJECT_CLASSES

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
    d.add(
        f"ou=people,{PARIS}",
        {"objectClass": [b"top", b"organizationalUnit"], "ou": [b"people"]},
    )
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            *PLUGIN_OBJECT_CLASSES,
            "nisNetgroup",
        ]
    )
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    classes = {c.lower() for c in directory.schema_object_classes()}
    reg.register_plugin(systems.plugin(), classes)
    status = reg.register_plugin(netgroups.plugin(), classes)
    assert status.enabled
    return reg


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def test_triple_parsing_and_formatting() -> None:
    assert netgroups.parse_triple("(host,user,domain)") == ("host", "user", "domain")
    assert netgroups.parse_triple("(-,alice,)") == ("-", "alice", "")
    assert netgroups.parse_triple("(srv1,-,example.com)") == ("srv1", "-", "example.com")
    assert netgroups.parse_triple("(,,)") == ("", "", "")
    assert netgroups.parse_triple("invalid") is None
    assert netgroups.parse_triple("(too,many,parts,here)") is None

    assert netgroups.format_triple("h", "u", "d") == "(h,u,d)"
    assert netgroups.format_triple(user="alice") == "(,alice,)"


def test_netgroup_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    values: dict[str, Any] = {
        "cn": "sysadmins",
        "description": "System Administrators",
        "memberNisNetgroup": ["staff"],
        "nisNetgroupTriple": ["(-,alice,)", "(-,bob,)"],
    }
    dn = service.create("netgroup", PARIS, {"main": {"values": values}})
    assert dn == f"cn=sysadmins,ou=netgroups,{PARIS}"

    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("cn") == "sysadmins"
    assert entry.text("description") == "System Administrators"
    assert sorted(entry.texts("nisNetgroupTriple")) == ["(-,alice,)", "(-,bob,)"]
    assert entry.texts("memberNisNetgroup") == ["staff"]

    loaded = service.load("netgroup", dn)
    assert loaded.tabs["main"].values["cn"] == "sysadmins"
    # Virtual memberUsers should extract alice and bob
    assert sorted(loaded.tabs["main"].values["memberUsers"]) == ["alice", "bob"]

    # Update description
    service.update("netgroup", dn, {"main": {"values": {"description": "Updated Administrators"}}})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("description") == "Updated Administrators"

    # Delete
    service.delete("netgroup", dn)
    assert directory.get(dn) is None


def test_netgroup_triple_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "netgroup",
            PARIS,
            {"main": {"values": {"cn": "bad-ng", "nisNetgroupTriple": ["not-a-triple"]}}},
        )
    assert "main.nisNetgroupTriple" in exc_info.value.fields


def test_user_membership_tab_sync(service: ObjectService, directory: MemoryDirectory) -> None:
    # 1. Create a netgroup
    ng_dn = service.create(
        "netgroup",
        PARIS,
        {"main": {"values": {"cn": "developers", "description": "Dev team"}}},
    )

    # 2. Create a user with membership in the netgroup
    user_values: dict[str, Any] = {
        "uid": "jdoe",
        "sn": "Doe",
        "givenName": "John",
    }
    tabs = {
        "main": {"values": user_values},
        "netgroup": {"values": {"nisMembership": [ng_dn]}},
    }
    user_dn = service.create("user", PARIS, tabs)

    # Verify that the netgroup entry now has (-,jdoe,)
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None
    assert "(-,jdoe,)" in ng_entry.texts("nisNetgroupTriple")

    # 3. Load user: nisMembership should contain ng_dn
    loaded_user = service.load("user", user_dn)
    assert loaded_user.tabs["netgroup"].values["nisMembership"] == [ng_dn]

    # 4. Remove membership
    service.update("user", user_dn, {"netgroup": {"values": {"nisMembership": []}}})
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None
    assert "(-,jdoe,)" not in ng_entry.texts("nisNetgroupTriple")

    # 5. Add back and delete user
    service.update("user", user_dn, {"netgroup": {"values": {"nisMembership": [ng_dn]}}})
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None and "(-,jdoe,)" in ng_entry.texts("nisNetgroupTriple")

    service.delete("user", user_dn)
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None
    assert "(-,jdoe,)" not in ng_entry.texts("nisNetgroupTriple")


class _NoMembershipRead:
    """Policy: everything allowed except reading the virtual nisMembership."""

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return attr != "nisMembership"

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_create(self, type_name: str, base: str) -> bool:
        return True

    def can_delete(self, dn: str, type_name: str) -> bool:
        return True


def test_saving_without_read_access_to_the_memberships_keeps_them(
    service: ObjectService, directory: MemoryDirectory, registry: TypeRegistry
) -> None:
    ng_dn = service.create("netgroup", PARIS, {"main": {"values": {"cn": "dev"}}})
    user_dn = service.create(
        "user",
        PARIS,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "netgroup": {"values": {"nisMembership": [ng_dn]}},
        },
    )
    restricted = ObjectService(directory, registry, policy=_NoMembershipRead())
    restricted.update("user", user_dn, {"main": {"values": {"description": "edited"}}})
    entry = directory.get(ng_dn) or pytest.fail()
    assert "(-,jdoe,)" in entry.texts("nisNetgroupTriple")


def test_membership_dns_are_compared_normalised(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    ng_dn = service.create("netgroup", PARIS, {"main": {"values": {"cn": "dev"}}})
    user_dn = service.create(
        "user",
        PARIS,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "netgroup": {"values": {"nisMembership": [ng_dn]}},
        },
    )
    shouted = ng_dn.upper().replace("DC=TEST", "dc=test")
    service.update("user", user_dn, {"netgroup": {"values": {"nisMembership": [shouted]}}})
    entry = directory.get(ng_dn) or pytest.fail()
    assert entry.texts("nisNetgroupTriple").count("(-,jdoe,)") == 1


def test_system_membership_tab_sync(service: ObjectService, directory: MemoryDirectory) -> None:
    # 1. Create a netgroup
    ng_dn = service.create(
        "netgroup",
        PARIS,
        {"main": {"values": {"cn": "webservers", "description": "Web hosts"}}},
    )

    # 2. Create a server with membership in the netgroup
    srv_values: dict[str, Any] = {
        "cn": "srv-web-01",
        "description": "Production web server",
    }
    tabs = {
        "main": {"values": srv_values},
        "netgroup": {"values": {"nisMembership": [ng_dn]}},
    }
    srv_dn = service.create("server", PARIS, tabs)

    # Verify that the netgroup entry has (srv-web-01,-,)
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None
    assert "(srv-web-01,-,)" in ng_entry.texts("nisNetgroupTriple")

    # 3. Load server
    loaded_srv = service.load("server", srv_dn)
    assert loaded_srv.tabs["netgroup"].values["nisMembership"] == [ng_dn]

    # 4. Remove membership
    service.update("server", srv_dn, {"netgroup": {"values": {"nisMembership": []}}})
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None
    assert "(srv-web-01,-,)" not in ng_entry.texts("nisNetgroupTriple")

    # 5. Delete server
    service.update("server", srv_dn, {"netgroup": {"values": {"nisMembership": [ng_dn]}}})
    service.delete("server", srv_dn)
    ng_entry = directory.get(ng_dn)
    assert ng_entry is not None
    assert "(srv-web-01,-,)" not in ng_entry.texts("nisNetgroupTriple")


class _NoNetgroupWrite(_NoMembershipRead):
    """Policy: everything allowed except changing the triples of a netgroup."""

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return attr != "nisNetgroupTriple"


def test_memberships_need_the_right_to_change_the_netgroup(
    service: ObjectService, directory: MemoryDirectory, registry: TypeRegistry
) -> None:
    ng_dn = service.create("netgroup", PARIS, {"main": {"values": {"cn": "dev"}}})
    restricted = ObjectService(directory, registry, policy=_NoNetgroupWrite())
    values = {"uid": "jdoe", "sn": "Doe", "givenName": "John"}
    with pytest.raises(ObjectValidationError) as refused:
        restricted.create(
            "user",
            PARIS,
            {"main": {"values": values}, "netgroup": {"values": {"nisMembership": [ng_dn]}}},
        )
    assert "netgroup.nisMembership" in refused.value.fields
    user_dn = service.create(
        "user",
        PARIS,
        {"main": {"values": values}, "netgroup": {"values": {"nisMembership": [ng_dn]}}},
    )
    with pytest.raises(ObjectValidationError):
        restricted.update("user", user_dn, {"netgroup": {"values": {"nisMembership": []}}})
    entry = directory.get(ng_dn) or pytest.fail()
    assert "(-,jdoe,)" in entry.texts("nisNetgroupTriple")


def test_renaming_a_user_does_not_leave_the_old_login_in_the_netgroups(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    ng_dn = service.create("netgroup", PARIS, {"main": {"values": {"cn": "dev"}}})
    user_dn = service.create(
        "user",
        PARIS,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "netgroup": {"values": {"nisMembership": [ng_dn]}},
        },
    )
    service.update("user", user_dn, {"main": {"values": {"uid": "jsmith"}}})
    triples = (directory.get(ng_dn) or pytest.fail()).texts("nisNetgroupTriple")
    assert triples == ["(-,jsmith,)"]
