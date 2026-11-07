"""Mixed groups: a groupOfNames that is also a posixGroup."""

from __future__ import annotations

import pytest

import heracles_plugins.dyngroups as dyn
import heracles_plugins.mixedgroups as mixed
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, Plugin, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"


def user_dn(uid: str) -> str:
    return f"uid={uid},{PEOPLE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(GROUPS, {"objectClass": [b"organizationalUnit"], "ou": [b"groups"]})
    for uid in ("alice", "bob", "carol"):
        d.add(
            user_dn(uid),
            {
                "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
                "uid": [uid.encode()],
                "cn": [uid.encode()],
                "sn": [uid.encode()],
                "departmentNumber": [b"sales" if uid != "carol" else b"it"],
            },
        )
    d.set_schema_object_classes([*d.schema_object_classes(), "groupOfURLs", "extensibleObject"])
    return d


def make_service(directory: MemoryDirectory, *plugins: Plugin) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    available = {c.lower() for c in directory.schema_object_classes()}
    for plugin in plugins:
        assert registry.register_plugin(plugin, available).enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory, mixed.plugin())


def new_group(service: ObjectService, members: list[str], **mixed_values: object) -> str:
    return service.create(
        "group",
        BASE,
        {
            "main": {"values": {"cn": "staff", "member": members}},
            "mixed": {"active": True, "values": mixed_values},
        },
    )


def test_acl_key(service: ObjectService) -> None:
    info = service.registry.get("group")
    tab = info.tab("mixed")
    assert tab is not None and info.acl_object(tab) == "ogroup/mixedGroup"


def test_activation_allocates_gid_and_syncs_member_uid(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group = new_group(service, [user_dn("alice"), user_dn("bob")])
    entry = directory.get(group) or pytest.fail()
    assert entry.has_object_class("groupOfNames") and entry.has_object_class("posixGroup")
    assert entry.text("gidNumber") == "1101"
    assert entry.texts("memberUid") == ["alice", "bob"]
    state = service.load("group", group)
    assert state.tabs["mixed"].values["gidNumber"] == 1101


def test_member_changes_update_member_uid_and_keep_the_gid(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group = new_group(service, [user_dn("alice")])
    service.update(
        "group", group, {"main": {"values": {"member": [user_dn("bob"), user_dn("carol")]}}}
    )
    entry = directory.get(group) or pytest.fail()
    assert entry.texts("memberUid") == ["bob", "carol"]
    assert entry.text("gidNumber") == "1101"


def test_existing_group_gets_a_new_gid(service: ObjectService, directory: MemoryDirectory) -> None:
    directory.add(
        f"cn=old,{GROUPS}",
        {"objectClass": [b"posixGroup"], "cn": [b"old"], "gidNumber": [b"1101"]},
    )
    group = new_group(service, [user_dn("alice")])
    assert (directory.get(group) or pytest.fail()).text("gidNumber") == "1102"


def test_forced_gid_must_be_free(service: ObjectService, directory: MemoryDirectory) -> None:
    directory.add(
        f"cn=old,{GROUPS}",
        {"objectClass": [b"posixGroup"], "cn": [b"old"], "gidNumber": [b"5000"]},
    )
    with pytest.raises(ObjectValidationError) as taken:
        new_group(service, [user_dn("alice")], force_id=True, gidNumber=5000)
    assert "mixed.gidNumber" in taken.value.fields
    with pytest.raises(ObjectValidationError):
        new_group(service, [user_dn("alice")], force_id=True)
    group = new_group(service, [user_dn("alice")], force_id=True, gidNumber=5001)
    assert (directory.get(group) or pytest.fail()).text("gidNumber") == "5001"


def test_deactivation_removes_posix_attributes(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group = new_group(service, [user_dn("alice")])
    service.update("group", group, {"mixed": {"active": False}})
    entry = directory.get(group) or pytest.fail()
    assert not entry.has_object_class("posixGroup")
    assert entry.get("memberUid") == [] and entry.get("gidNumber") == []
    assert entry.texts("member") == [user_dn("alice")]


@pytest.mark.parametrize("dynamic_first", [True, False])
def test_works_with_dynamic_groups_in_any_plugin_order(
    directory: MemoryDirectory, dynamic_first: bool
) -> None:
    plugins = [dyn.plugin(), mixed.plugin()]
    service = make_service(directory, *(plugins if dynamic_first else plugins[::-1]))
    group = service.create(
        "group",
        BASE,
        {
            "main": {"values": {"cn": "sales"}},
            "dynamic": {"active": True, "values": {"memberURL": "(departmentNumber=sales)"}},
            "mixed": {"active": True},
        },
    )
    entry = directory.get(group) or pytest.fail()
    assert sorted(entry.texts("memberUid")) == ["alice", "bob"]
    assert entry.text("gidNumber") == "1101"
