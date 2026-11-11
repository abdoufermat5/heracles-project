"""Samba plugin: hashes, flags, SIDs, user/group/workstation tabs, domain type."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest

import heracles_plugins.posix as posix
import heracles_plugins.samba as samba
from heracles.attributes import set_default_password_hasher
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.names import PLUGIN_OBJECT_CLASSES
from heracles_plugins import systems
from heracles_plugins.samba.flags import (
    LogonHoursAttr,
    UnixDateAttr,
    WorkstationsAttr,
    format_flags,
    grid_to_hours,
    hours_to_grid,
    parse_flags,
    set_flag,
)
from heracles_plugins.samba.hashes import des_encrypt_block, lm_hash, md4, nt_hash

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
DOMAIN_SID = "S-1-5-21-111-222-333"
NOW = 1_700_000_000

SAMBA_CLASSES = [
    "sambaSamAccount",
    "sambaGroupMapping",
    "sambaDomain",
    "sambaIdmapEntry",
    "sambaUnixIdPool",
]


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(samba, "now_epoch", lambda: NOW)
    set_default_password_hasher(lambda p: "{TEST}" + p)
    yield
    set_default_password_hasher(None)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for ou in ("people", "groups"):
        d.add(f"ou={ou},{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.set_schema_object_classes(
        [*d.schema_object_classes(), *PLUGIN_OBJECT_CLASSES, *SAMBA_CLASSES]
    )
    return d


def build(directory: MemoryDirectory, settings: samba.SambaSettings | None = None) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    available = {c.lower() for c in directory.schema_object_classes()}
    for plugin in (posix.plugin(), systems.plugin(), samba.plugin()):
        assert registry.register_plugin(plugin, available).enabled
    registry.settings["samba"] = settings or samba.SambaSettings(domain_sid=DOMAIN_SID)
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return build(directory)


def new_user(
    service: ObjectService,
    uid: str = "jdoe",
    samba_values: dict[str, Any] | None = None,
    main: dict[str, Any] | None = None,
) -> str:
    tabs: dict[str, Any] = {
        "main": {"values": {"uid": uid, "givenName": "John", "sn": "Doe", **(main or {})}},
        "posix": {"active": True, "values": {}},
        "samba": {"active": True, "values": samba_values or {}},
    }
    return service.create("user", BASE, tabs)


def new_group(
    service: ObjectService, cn: str = "staff", samba_values: dict[str, Any] | None = None
) -> str:
    return service.create(
        "posix_group",
        BASE,
        {"main": {"values": {"cn": cn}}, "samba": {"active": True, "values": samba_values or {}}},
    )


def entry_of(directory: MemoryDirectory, dn: str) -> Any:
    entry = directory.get(dn)
    assert entry is not None
    return entry


# ------------------------------------------------------------------ hashes


def test_md4_rfc1320_vectors() -> None:
    assert md4(b"").hex() == "31d6cfe0d16ae931b73c59d7e0c089c0"
    assert md4(b"a").hex() == "bde52cb31de33e46245e05fbdbd6fb24"
    assert md4(b"abc").hex() == "a448017aaf21d8525fc10ae87aa6729d"
    assert md4(b"message digest").hex() == "d9130a8164549fe818874806e1c7014b"
    assert md4(b"abcdefghijklmnopqrstuvwxyz").hex() == "d79e1c308aa5bbcdeea8ed63df412da9"
    long = b"1234567890" * 8
    assert md4(long).hex() == "e33b4ddc9c38f2199c3e7b164fcc0536"


def test_nt_hash_vectors() -> None:
    assert nt_hash("password") == "8846F7EAEE8FB117AD06BDD830B7586C"
    assert nt_hash("") == "31D6CFE0D16AE931B73C59D7E0C089C0"


def test_des_vector() -> None:
    out = des_encrypt_block(bytes.fromhex("133457799BBCDFF1"), bytes.fromhex("0123456789ABCDEF"))
    assert out.hex() == "85e813540f0ab405"


def test_lm_hash_vectors() -> None:
    assert lm_hash("password") == "E52CAC67419A9A224A3B108F3FA6CB6D"
    assert lm_hash("PASSWORD") == lm_hash("password")
    assert lm_hash("") == "AAD3B435B51404EEAAD3B435B51404EE"
    assert lm_hash("x" * 15) is None
    assert lm_hash("pässwörd€") is None


# ------------------------------------------------------------- flags, hours


def test_flag_format_and_parse() -> None:
    assert format_flags("UX") == "[UX         ]"
    assert len(format_flags("UX")) == 13
    assert format_flags("XU") == "[UX         ]"
    assert parse_flags("[UX         ]") == "UX"
    assert parse_flags("garbage") == ""
    assert parse_flags(None) == ""


def test_flag_preserves_unknown_letters() -> None:
    letters = set_flag(parse_flags("[UQD        ]"), "D", on=False)
    assert format_flags(letters) == "[UQ         ]"


def test_logon_hours_grid_round_trip() -> None:
    assert all(all(day) for day in hours_to_grid(None))
    grid = [[False] * 24 for _ in range(7)]
    grid[0][0] = True  # Sunday 00:00 is the first bit
    grid[6][23] = True
    text = grid_to_hours(grid)
    assert len(text) == 42
    assert text.startswith("01")
    assert text.endswith("80")
    assert hours_to_grid(text) == grid
    assert grid_to_hours(hours_to_grid("F" * 42)) == "F" * 42


def test_attribute_validation() -> None:
    hours = LogonHoursAttr("sambaLogonHours", "h")
    assert hours.validate("F" * 42) == []
    assert hours.validate("F" * 41)
    assert hours.validate("Z" * 42)
    ws = WorkstationsAttr("sambaUserWorkstations", "w")
    assert ws.validate("pc1,pc2") == []
    assert ws.validate("pc1,,pc2")
    assert ws.validate("pc1,PC1")


def test_unix_date_attr() -> None:
    attr = UnixDateAttr("sambaKickoffTime", "k")
    assert attr.to_ldap(date(2024, 1, 2)) == [b"1704153600"]
    assert attr.from_ldap([b"1704153600"]) == date(2024, 1, 2)
    assert attr.from_ldap([b"2147483647"]) is None
    assert attr.from_ldap([b"nope"]) is None


# ---------------------------------------------------------------- user tab


def test_user_tab_computes_sid_and_primary_group(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(service)
    entry = entry_of(directory, dn)
    assert entry.has_object_class("sambaSamAccount")
    uid_number = int(entry.text("uidNumber"))
    assert entry.text("sambaSID") == f"{DOMAIN_SID}-{uid_number * 2 + 1000}"
    assert entry.text("sambaPrimaryGroupSID") == f"{DOMAIN_SID}-513"
    assert entry.text("sambaAcctFlags") == "[U          ]"
    for virtual in ("flag_disabled", "hrc_pwdCantChange", "wellKnownRid", "primaryGroupStatus"):
        assert not entry.get(virtual)


def test_primary_group_sid_uses_group_mapping(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    group = new_group(service)
    gid = int(entry_of(directory, group).text("gidNumber"))
    group_sid = entry_of(directory, group).text("sambaSID")
    assert group_sid == f"{DOMAIN_SID}-{gid * 2 + 1000 + 1}"
    dn = new_user(service)
    posix_tab = {"posix": {"values": {"primaryGroup": group}}}
    service.update("user", dn, posix_tab)
    service.update("user", dn, {"samba": {"values": {"sambaDomainName": ""}}})
    assert entry_of(directory, dn).text("gidNumber") == str(gid)
    assert entry_of(directory, dn).text("sambaPrimaryGroupSID") == group_sid


def test_sid_collision_increments(service: ObjectService, directory: MemoryDirectory) -> None:
    first = new_user(service, "a")
    uid_number = int(entry_of(directory, first).text("uidNumber"))
    taken = f"{DOMAIN_SID}-{(uid_number + 1) * 2 + 1000}"
    directory.add(
        f"cn=other,{GROUPS}",
        {"objectClass": [b"sambaGroupMapping"], "cn": [b"other"], "sambaSID": [taken.encode()]},
    )
    second = new_user(service, "b")
    assert (
        entry_of(directory, second).text("sambaSID")
        == f"{DOMAIN_SID}-{(uid_number + 1) * 2 + 1001}"
    )


def test_requires_posix_tab(service: ObjectService) -> None:
    tabs = {
        "main": {"values": {"uid": "jdoe", "givenName": "John", "sn": "Doe"}},
        "samba": {"active": True},
    }
    with pytest.raises(ObjectValidationError) as exc:
        service.create("user", BASE, tabs)
    assert "samba.sambaDomainName" in exc.value.fields


def test_posix_not_required_when_disabled(directory: MemoryDirectory) -> None:
    service = build(directory, samba.SambaSettings(domain_sid=DOMAIN_SID, depends_on_posix=False))
    tabs = {
        "main": {"values": {"uid": "jdoe", "givenName": "John", "sn": "Doe"}},
        "samba": {"active": True},
    }
    dn = service.create("user", BASE, tabs)
    assert entry_of(directory, dn).text("sambaSID") == f"{DOMAIN_SID}-1000"


def test_missing_domain_is_an_error(directory: MemoryDirectory) -> None:
    service = build(directory, samba.SambaSettings())
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service)
    assert "samba.sambaDomainName" in exc.value.fields


def test_domain_entry_supplies_sid_and_rid_base(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    service.create(
        "samba_domain",
        BASE,
        {
            "main": {
                "values": {
                    "sambaDomainName": "CORP",
                    "sambaSID": "S-1-5-21-9-9-9",
                    "sambaAlgorithmicRidBase": 500,
                }
            }
        },
    )
    dn = new_user(service, samba_values={"sambaDomainName": "CORP"})
    entry = entry_of(directory, dn)
    assert entry.text("sambaDomainName") == "CORP"
    assert entry.text("sambaSID") == f"S-1-5-21-9-9-9-{int(entry.text('uidNumber')) * 2 + 500}"


def test_single_domain_is_the_default(directory: MemoryDirectory) -> None:
    service = build(directory, samba.SambaSettings())
    service.create(
        "samba_domain",
        BASE,
        {"main": {"values": {"sambaDomainName": "ONLY", "sambaSID": "S-1-5-21-5-5-5"}}},
    )
    dn = new_user(service)
    assert entry_of(directory, dn).text("sambaDomainName") == "ONLY"


def test_password_writes_hashes_and_last_set(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(service, main={"userPassword": "password"})
    entry = entry_of(directory, dn)
    assert entry.text("sambaNTPassword") == "8846F7EAEE8FB117AD06BDD830B7586C"
    assert entry.get("sambaLMPassword") == []
    assert entry.text("sambaPwdLastSet") == str(NOW)
    assert entry.text("userPassword") == "{TEST}password"  # stored hashed by the main tab


def test_lm_password_only_when_enabled(directory: MemoryDirectory) -> None:
    service = build(
        directory, samba.SambaSettings(domain_sid=DOMAIN_SID, generate_lm_password=True)
    )
    dn = new_user(service, main={"userPassword": "password"})
    assert entry_of(directory, dn).text("sambaLMPassword") == "E52CAC67419A9A224A3B108F3FA6CB6D"
    service.update("user", dn, {"main": {"values": {"userPassword": "x" * 20}}})
    entry = entry_of(directory, dn)
    assert entry.get("sambaLMPassword") == []
    assert entry.text("sambaNTPassword") == nt_hash("x" * 20)


def test_hashes_are_not_exposed(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service, main={"userPassword": "password"})
    state = service.load("user", dn)
    assert state.tabs["samba"].values["sambaNTPassword"] is None
    tab = next(t for t in service.registry.get("user").tabs if t.name == "samba")
    exposed = state.to_json([tab])["tabs"]["samba"]["values"]  # type: ignore[index]
    assert exposed["sambaNTPassword"] is None  # type: ignore[index]


def test_unrelated_update_keeps_hashes(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service, main={"userPassword": "password"})
    service.update("user", dn, {"samba": {"values": {"sambaHomePath": r"\\srv\home"}}})
    entry = entry_of(directory, dn)
    assert entry.text("sambaNTPassword") == nt_hash("password")
    assert entry.text("sambaHomePath") == r"\\srv\home"
    assert entry.text("sambaPwdLastSet") == str(NOW)


def test_password_cannot_change_flag(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service, samba_values={"hrc_pwdCantChange": True}, main={"userPassword": "pw"})
    assert entry_of(directory, dn).text("sambaPwdLastSet") == "4294967295"
    state = service.load("user", dn)
    assert state.tabs["samba"].values["hrc_pwdCantChange"] is True
    service.update("user", dn, {"samba": {"values": {"hrc_pwdCantChange": False}}})
    assert entry_of(directory, dn).text("sambaPwdLastSet") == str(NOW)


def test_flags_are_composed_and_unknown_letters_kept(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(
        service,
        samba_values={"flag_disabled": True, "flag_pwdNeverExpires": True},
    )
    assert entry_of(directory, dn).text("sambaAcctFlags") == "[DUX        ]"
    directory.modify(dn, [Modification("replace", "sambaAcctFlags", [b"[UXQL       ]"])])
    service.update("user", dn, {"samba": {"values": {"flag_noPwdRequired": True}}})
    assert entry_of(directory, dn).text("sambaAcctFlags") == "[NULXQ      ]"
    state = service.load("user", dn)
    assert state.tabs["samba"].values["flag_autoLocked"] is True


def test_expiration_sync_posix_to_samba(directory: MemoryDirectory) -> None:
    service = build(directory, samba.SambaSettings(domain_sid=DOMAIN_SID, expiration_sync="posix"))
    tabs = {
        "main": {"values": {"uid": "jdoe", "givenName": "John", "sn": "Doe"}},
        "posix": {"active": True, "values": {"shadowExpire": "2024-01-02"}},
        "samba": {"active": True},
    }
    dn = service.create("user", BASE, tabs)
    assert entry_of(directory, dn).text("sambaKickoffTime") == "1704153600"
    assert entry_of(directory, dn).text("shadowExpire") == "19724"


def test_expiration_sync_samba_to_posix(directory: MemoryDirectory) -> None:
    service = build(directory, samba.SambaSettings(domain_sid=DOMAIN_SID, expiration_sync="samba"))
    dn = new_user(service, samba_values={"sambaKickoffTime": "2024-01-02"})
    assert entry_of(directory, dn).text("shadowExpire") == "19724"
    assert entry_of(directory, dn).text("sambaKickoffTime") == "1704153600"


def test_no_expiration_sync_by_default(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service, samba_values={"sambaKickoffTime": "2024-01-02"})
    assert entry_of(directory, dn).get("shadowExpire") == []


def test_logon_hours_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, samba_values={"sambaLogonHours": "ABC"})
    assert "samba.sambaLogonHours" in exc.value.fields


def test_munged_dial_is_untouched(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_user(service)
    directory.modify(dn, [Modification("add", "sambaMungedDial", [b"\x00blob"])])
    service.update("user", dn, {"samba": {"values": {"sambaHomePath": "x"}}})
    assert entry_of(directory, dn).first("sambaMungedDial") == b"\x00blob"


def test_deactivating_removes_samba_attributes(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(service, main={"userPassword": "pw"})
    service.update("user", dn, {"samba": {"active": False}})
    entry = entry_of(directory, dn)
    assert not entry.has_object_class("sambaSamAccount")
    assert entry.get("sambaSID") == [] and entry.get("sambaNTPassword") == []
    assert entry.has_object_class("posixAccount")


def test_lock_hook() -> None:
    from heracles.ldap.client import Entry

    entry = Entry(
        "uid=a,dc=test",
        {"objectClass": [b"sambaSamAccount"], "sambaAcctFlags": [b"[UX         ]"]},
    )
    (mod,) = samba.lock_account(entry, True)
    assert mod.values == [b"[DUX        ]"]
    locked = Entry(
        "uid=a,dc=test",
        {"objectClass": [b"sambaSamAccount"], "sambaAcctFlags": [b"[DUX        ]"]},
    )
    (mod,) = samba.lock_account(locked, False)
    assert mod.values == [b"[UX         ]"]
    assert samba.lock_account(locked, True) == []
    assert samba.lock_account(Entry("uid=b,dc=test", {"objectClass": [b"person"]}), True) == []


def test_account_lock_hook_is_registered(service: ObjectService) -> None:
    assert samba.lock_account in service.registry.account_lock_hooks


def test_id_mapping_adds_and_removes_class(directory: MemoryDirectory) -> None:
    service = build(directory, samba.SambaSettings(domain_sid=DOMAIN_SID, id_mapping=True))
    dn = new_user(service)
    assert entry_of(directory, dn).has_object_class("sambaIdmapEntry")
    group = new_group(service)
    assert entry_of(directory, group).has_object_class("sambaIdmapEntry")
    service.update("user", dn, {"samba": {"active": False}})
    assert not entry_of(directory, dn).has_object_class("sambaIdmapEntry")


def test_no_id_mapping_by_default(service: ObjectService, directory: MemoryDirectory) -> None:
    assert not entry_of(directory, new_user(service)).has_object_class("sambaIdmapEntry")


# --------------------------------------------------------------- group tab


def test_group_tab_defaults(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_group(service)
    entry = entry_of(directory, dn)
    assert entry.has_object_class("sambaGroupMapping")
    assert entry.text("sambaGroupType") == "2"
    assert entry.text("displayName") == "staff"
    assert entry.get("wellKnownRid") == []


def test_group_well_known_rid(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_group(service, "admins", {"wellKnownRid": "512"})
    assert entry_of(directory, dn).text("sambaSID") == f"{DOMAIN_SID}-512"
    assert service.load("posix_group", dn).tabs["samba"].values["wellKnownRid"] == "512"
    with pytest.raises(ObjectValidationError) as exc:
        new_group(service, "admins2", {"wellKnownRid": "512"})
    assert "samba.wellKnownRid" in exc.value.fields


def test_group_alias_defaults_to_local_type(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_group(service, "adm", {"wellKnownRid": "544"})
    assert entry_of(directory, dn).text("sambaGroupType") == "4"


def test_group_invalid_well_known_rid(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError):
        new_group(service, "g", {"wellKnownRid": "999"})


# ---------------------------------------------------------- workstation tab


def test_workstation_machine_account(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "workstation",
        BASE,
        {"main": {"values": {"cn": "pc01"}}, "samba": {"active": True}},
    )
    entry = entry_of(directory, dn)
    assert entry.has_object_class("posixAccount") and entry.has_object_class("sambaSamAccount")
    assert entry.text("uid") == "pc01$"
    assert entry.text("sambaAcctFlags") == "[W          ]"
    assert entry.text("sambaPrimaryGroupSID") == f"{DOMAIN_SID}-515"
    assert entry.text("sambaSID") == f"{DOMAIN_SID}-{int(entry.text('uidNumber')) * 2 + 1000}"
    assert entry.text("homeDirectory") == "/dev/null"
    assert entry.text("loginShell") == "/bin/false"
    assert entry.text("gidNumber") == "515"


def test_workstation_rename_updates_uid(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "workstation", BASE, {"main": {"values": {"cn": "pc01"}}, "samba": {"active": True}}
    )
    uid_number = entry_of(directory, dn).text("uidNumber")
    new_dn = service.update("workstation", dn, {"main": {"values": {"cn": "pc02"}}}).dn
    entry = entry_of(directory, new_dn)
    assert entry.text("uid") == "pc02$"
    assert entry.text("uidNumber") == uid_number


# -------------------------------------------------------------- domain type


def test_domain_type(service: ObjectService, directory: MemoryDirectory) -> None:
    info = service.registry.get("samba_domain")
    assert info.acl_object(info.main_tab) == "sambaDomain/sambaDomain"
    dn = service.create(
        "samba_domain",
        BASE,
        {"main": {"values": {"sambaDomainName": "CORP", "sambaSID": DOMAIN_SID}}},
    )
    assert dn == f"sambaDomainName=CORP,{BASE}"
    with pytest.raises(ObjectValidationError):
        service.create(
            "samba_domain", BASE, {"main": {"values": {"sambaDomainName": "X", "sambaSID": "bad"}}}
        )


def test_acl_keys(service: ObjectService) -> None:
    user = service.registry.get("user")
    group = service.registry.get("posix_group")
    station = service.registry.get("workstation")
    assert user.acl_object(user.tab("samba")) == "user/sambaAccount"  # type: ignore[arg-type]
    assert group.acl_object(group.tab("samba")) == "group/sambaGroup"  # type: ignore[arg-type]
    assert station.acl_object(station.tab("samba")) == "workstation/sambaSystemTab"  # type: ignore[arg-type]


def test_plugin_disabled_without_schema() -> None:
    d = MemoryDirectory(BASE)
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        samba.plugin(), {c.lower() for c in d.schema_object_classes()}
    )
    assert not status.enabled
