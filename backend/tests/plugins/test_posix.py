"""POSIX plugin: id allocation, personal groups, membership, shadow fields."""

from __future__ import annotations

from datetime import date

import pytest

import heracles_plugins.posix as posix
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.posix import EpochDaysAttr, ascii_gecos, posix_status
from heracles_plugins.posix.ids import next_free_id, parse_range

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
TODAY = 20_000


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(posix, "today_epoch_days", lambda: TODAY)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(GROUPS, {"objectClass": [b"organizationalUnit"], "ou": [b"groups"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        posix.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def new_user(
    service: ObjectService, uid: str = "jdoe", posix_values: dict[str, object] | None = None
) -> str:
    tabs: dict[str, object] = {
        "main": {"values": {"uid": uid, "givenName": "Jérôme", "sn": "Doe"}},
        "posix": {"active": True, "values": posix_values or {}},
    }
    return service.create("user", BASE, tabs)


def posix_group(directory: MemoryDirectory, cn: str, gid: int, members: list[str] = ()) -> str:  # type: ignore[assignment]
    dn = f"cn={cn},{GROUPS}"
    attrs = {"objectClass": [b"posixGroup"], "cn": [cn.encode()], "gidNumber": [str(gid).encode()]}
    if members:
        attrs["memberUid"] = [m.encode() for m in members]
    directory.add(dn, attrs)
    return dn


# ------------------------------------------------------------------- ids


def test_parse_range() -> None:
    assert parse_range("1100") == (1100, 2**32)
    assert parse_range("1100-1200") == (1100, 1200)


def test_next_free_id_starts_after_base_and_skips_used(directory: MemoryDirectory) -> None:
    assert next_free_id(directory, "posixGroup", "gidNumber", base="1100") == 1101
    posix_group(directory, "a", 1101)
    posix_group(directory, "b", 1102)
    assert next_free_id(directory, "posixGroup", "gidNumber", base="1100") == 1103
    assert next_free_id(directory, "posixGroup", "gidNumber", base="1100", min_id=2000) == 2000


def test_next_free_id_exhausted(directory: MemoryDirectory) -> None:
    posix_group(directory, "a", 11)
    with pytest.raises(posix.IdAllocationError):
        next_free_id(directory, "posixGroup", "gidNumber", base="10-12")


# ------------------------------------------------------------ account tab


def test_activation_allocates_ids_and_creates_personal_group(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(service)
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("posixAccount") and entry.has_object_class("shadowAccount")
    assert entry.text("uidNumber") == "1101"
    assert entry.text("gidNumber") == "1101"
    assert entry.text("homeDirectory") == "/home/jdoe"
    assert entry.text("loginShell") == "/bin/bash"
    assert entry.text("gecos") == "Jerome Doe"
    assert entry.text("shadowLastChange") == str(TODAY)
    group = directory.get(f"cn=jdoe,{GROUPS}")
    assert group is not None
    assert group.text("gidNumber") == "1101"
    assert group.text("description") == "Group of user jdoe"
    for virtual in ("primaryGroup", "force_ids", "groupMembership", "mustchangepassword"):
        assert not entry.get(virtual)


def test_existing_personal_group_is_reused(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    posix_group(directory, "jdoe", 1500)
    dn = new_user(service)
    entry = directory.get(dn)
    assert entry is not None and entry.text("gidNumber") == "1500"
    assert len(list(directory.search(BASE, "(cn=jdoe*)"))) == 1


def test_personal_group_name_collision_without_gid(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    directory.add(
        f"cn=jdoe,{GROUPS}", {"objectClass": [b"posixGroup"], "cn": [b"jdoe"], "gidNumber": [b"x"]}
    )
    new_user(service)
    assert directory.get(f"cn=jdoe_1,{GROUPS}") is not None


def test_selected_primary_group(service: ObjectService, directory: MemoryDirectory) -> None:
    staff = posix_group(directory, "staff", 2000)
    dn = new_user(service, posix_values={"primaryGroup": staff})
    entry = directory.get(dn)
    assert entry is not None and entry.text("gidNumber") == "2000"
    assert directory.get(f"cn=jdoe,{GROUPS}") is None
    state = service.load("user", dn)
    assert state.tabs["posix"].values["primaryGroup"] == staff


def test_forced_ids(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service, posix_values={"force_ids": True, "uidNumber": 4242, "gidNumber": 4343})
    entry = directory.get(dn)
    assert entry is not None
    assert (entry.text("uidNumber"), entry.text("gidNumber")) == ("4242", "4343")
    assert directory.get(f"cn=jdoe,{GROUPS}") is not None  # group with gid 4343 created


def test_forced_ids_require_values(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, posix_values={"force_ids": True})
    assert "posix.uidNumber" in exc.value.fields


def test_group_membership_is_stored_on_groups(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dev = posix_group(directory, "dev", 3000)
    ops = posix_group(directory, "ops", 3001, ["someone"])
    dn = new_user(service, posix_values={"groupMembership": [dev, ops]})
    assert service.load("user", dn).tabs["posix"].values["groupMembership"] == [dev, ops]
    dev_entry, ops_entry = directory.get(dev), directory.get(ops)
    assert dev_entry is not None and dev_entry.texts("memberUid") == ["jdoe"]
    assert ops_entry is not None and sorted(ops_entry.texts("memberUid")) == ["jdoe", "someone"]

    service.update("user", dn, {"posix": {"values": {"groupMembership": [ops]}}})
    dev_entry = directory.get(dev)
    assert dev_entry is not None and dev_entry.texts("memberUid") == []


def test_login_rename_follows_member_uid(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dev = posix_group(directory, "dev", 3000)
    dn = new_user(service, posix_values={"groupMembership": [dev]})
    service.update("user", dn, {"main": {"values": {"uid": "jdoe2"}}})
    entry = directory.get(dev)
    assert entry is not None and entry.texts("memberUid") == ["jdoe2"]


def test_must_change_password(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service, posix_values={"mustchangepassword": True, "shadowMax": 30})
    entry = directory.get(dn)
    assert entry is not None and entry.text("shadowLastChange") == str(TODAY - 31)
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, uid="other", posix_values={"mustchangepassword": True})
    assert "posix.shadowMax" in exc.value.fields


def test_password_change_updates_last_change(
    service: ObjectService, directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heracles.attributes import set_default_password_hasher

    set_default_password_hasher(lambda p, /: "{CLEAR}" + p)
    dn = new_user(service)
    monkeypatch.setattr(posix, "today_epoch_days", lambda: TODAY + 5)
    service.update("user", dn, {"main": {"values": {"userPassword": "new-secret"}}})
    entry = directory.get(dn)
    assert entry is not None and entry.text("shadowLastChange") == str(TODAY + 5)
    service.update("user", dn, {"main": {"values": {"sn": "Smith"}}})
    entry = directory.get(dn)
    assert entry is not None and entry.text("shadowLastChange") == str(TODAY + 5)


def test_deactivation_cleans_groups(service: ObjectService, directory: MemoryDirectory) -> None:
    dev = posix_group(directory, "dev", 3000)
    dn = new_user(service, posix_values={"groupMembership": [dev]})
    service.update("user", dn, {"posix": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None and not entry.has_object_class("posixAccount")
    assert not entry.get("uidNumber") and not entry.get("homeDirectory")
    dev_entry = directory.get(dev)
    assert dev_entry is not None and dev_entry.texts("memberUid") == []
    assert directory.get(f"cn=jdoe,{GROUPS}") is None


def test_delete_user_removes_personal_group_unless_shared(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(service)
    directory.modify(f"cn=jdoe,{GROUPS}", [Modification("add", "memberUid", [b"other"])])
    service.delete("user", dn)
    assert directory.get(f"cn=jdoe,{GROUPS}") is not None
    dn = new_user(service, uid="solo")
    service.delete("user", dn)
    assert directory.get(f"cn=solo,{GROUPS}") is None


# ------------------------------------------------------------ posix group


def test_posix_group_type(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "posix_group", BASE, {"main": {"values": {"cn": "devs", "memberUid": ["a", "b"]}}}
    )
    entry = directory.get(dn)
    assert entry is not None and entry.text("gidNumber") == "1101"
    assert entry.texts("memberUid") == ["a", "b"]
    forced = service.create(
        "posix_group", BASE, {"main": {"values": {"cn": "f", "force_gid": True, "gidNumber": 9}}}
    )
    forced_entry = directory.get(forced)
    assert forced_entry is not None and forced_entry.text("gidNumber") == "9"
    page = service.list("posix_group", BASE)
    assert {r.dn for r in page.items} == {dn, forced}


def test_groups_of_names_are_not_posix_groups(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    directory.add(
        f"cn=mixed,{GROUPS}",
        {
            "objectClass": [b"groupOfNames", b"posixGroup"],
            "cn": [b"mixed"],
            "gidNumber": [b"7"],
            "member": [b"cn=x"],
        },
    )
    assert service.list("posix_group", BASE).total == 0


# ---------------------------------------------------------------- helpers


def test_epoch_days_attribute() -> None:
    attr = EpochDaysAttr("shadowExpire", "x")
    assert attr.from_ldap([b"19723"]) == date(2024, 1, 1)
    assert attr.to_ldap(date(2024, 1, 1)) == [b"19723"]
    assert attr.from_ldap([b"0"]) is None
    assert attr.from_ldap([b"garbage"]) is None


def test_status() -> None:
    assert posix_status({}) == "active"
    assert posix_status({"shadowExpire": TODAY - 1}) == "expired"
    assert posix_status({"shadowExpire": TODAY - 1, "shadowInactive": 5}).endswith(
        "grace time active"
    )
    assert (
        posix_status({"shadowLastChange": str(TODAY - 40), "shadowMax": 30})
        == "active, password expired"
    )


def test_ascii_gecos() -> None:
    assert ascii_gecos("Chloé Dupont-Lefèvre") == "Chloe Dupont-Lefevre"
    assert ascii_gecos("Smith, John") == ""
