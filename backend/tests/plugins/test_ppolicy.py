"""Service-level tests for the ppolicy plugin."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import heracles_plugins.ppolicy as ppolicy
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectNotFoundError, ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.ppolicy import (
    DEFAULT_DURATION_UNIT,
    DurationAttr,
    PpolicySettings,
    PwdPolicySubentryAttr,
    unlock_account_hook,
)

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
PPOLICIES = f"ou=ppolicies,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    # ``device`` (structural class of the policy entries) is not in the default schema
    d.set_schema_object_classes(d.schema_object_classes() | {"device"})
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(PPOLICIES, {"objectClass": [b"organizationalUnit"], "ou": [b"ppolicies"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        ppolicy.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def new_policy(
    service: ObjectService,
    cn: str = "standard",
    values: dict[str, Any] | None = None,
) -> str:
    body: dict[str, Any] = {"cn": cn, **(values or {})}
    tabs: dict[str, Any] = {"main": {"values": body}}
    return service.create("ppolicy", BASE, tabs)


def new_user(
    service: ObjectService,
    uid: str = "jdoe",
    ppolicy_values: dict[str, Any] | None = None,
) -> str:
    tabs: dict[str, Any] = {
        "main": {"values": {"uid": uid, "givenName": "John", "sn": "Doe"}},
    }
    if ppolicy_values is not None:
        tabs["ppolicy"] = {"values": ppolicy_values}
    return service.create("user", BASE, tabs)


# ------------------------------------------------------------- plugin metadata


def test_plugin_metadata(directory: MemoryDirectory) -> None:
    plug = ppolicy.plugin()
    assert plug.name == "ppolicy"
    assert plug.required_object_classes == ("pwdPolicy",)

    registry = TypeRegistry()
    register_builtin_types(registry)
    # Missing pwdPolicy in available schema
    status_disabled = registry.register_plugin(plug, {"inetorgperson"})
    assert not status_disabled.enabled
    assert status_disabled.missing_object_classes == ["pwdPolicy"]

    # Available pwdPolicy in schema
    status_enabled = registry.register_plugin(plug, {"pwdpolicy"})
    assert status_enabled.enabled


# ------------------------------------------------------------- seconds conversion


def test_seconds_conversion_whole_units() -> None:
    attr = DurationAttr("pwdMaxAge", "Max age", unit_seconds=DEFAULT_DURATION_UNIT)
    assert attr.from_ldap([b"86400"]) == 1
    assert attr.to_ldap(1) == [b"86400"]
    assert attr.to_seconds(1) == 86400
    assert attr.from_seconds(86400) == 1

    # 90 days
    assert attr.from_ldap([b"7776000"]) == 90
    assert attr.to_ldap(90) == [b"7776000"]
    assert attr.to_seconds(90) == 7776000
    assert attr.from_seconds(7776000) == 90

    # 0 seconds / 0 days
    assert attr.from_ldap([b"0"]) == 0
    assert attr.to_ldap(0) == [b"0"]
    assert attr.from_ldap([]) is None
    assert attr.to_ldap(None) == []


def test_seconds_conversion_non_whole_values() -> None:
    attr = DurationAttr("pwdMinAge", "Min age", unit_seconds=DEFAULT_DURATION_UNIT)
    # Non-whole second values (e.g. 45 seconds or 12345 seconds) are kept as seconds
    assert attr.from_ldap([b"45"]) == 45
    assert attr.from_seconds(45) == 45
    assert attr.from_ldap([b"12345"]) == 12345
    assert attr.from_seconds(12345) == 12345

    # Invalid string returns None
    assert attr.from_ldap([b"invalid"]) is None


# ------------------------------------------------------------- policy CRUD


def test_policy_crud_flow(service: ObjectService, directory: MemoryDirectory) -> None:
    # 1. Create policy
    dn = new_policy(
        service,
        "developers",
        {
            "description": "Policy for developers",
            "pwdMinLength": 12,
            "pwdInHistory": 5,
            "pwdMinAge": 1,
            "pwdMaxAge": 90,
            "pwdExpireWarning": 14,
            "pwdLockoutDuration": 1,
            "pwdFailureCountInterval": 1,
            "pwdMustChange": True,
            "pwdAllowUserChange": True,
            "pwdSafeModify": False,
            "pwdLockout": True,
            "pwdMaxFailure": 3,
            "pwdCheckQuality": 2,
            "pwdGraceAuthNLimit": 0,
        },
    )
    assert dn == f"cn=developers,{PPOLICIES}"

    # Check stored LDAP entry
    raw = directory.get(dn)
    assert raw is not None
    assert raw.text("cn") == "developers"
    assert raw.text("description") == "Policy for developers"
    assert raw.text("pwdAttribute") == "userPassword"
    assert raw.text("pwdMinLength") == "12"
    assert raw.text("pwdInHistory") == "5"
    assert raw.text("pwdMinAge") == "86400"
    assert raw.text("pwdMaxAge") == "7776000"
    assert raw.text("pwdExpireWarning") == "1209600"
    assert raw.text("pwdLockoutDuration") == "86400"
    assert raw.text("pwdFailureCountInterval") == "86400"
    assert raw.text("pwdMustChange") == "TRUE"
    assert raw.text("pwdAllowUserChange") == "TRUE"
    assert raw.text("pwdSafeModify") == "FALSE"
    assert raw.text("pwdLockout") == "TRUE"
    assert raw.text("pwdMaxFailure") == "3"
    assert raw.text("pwdCheckQuality") == "2"

    # 2. Read / Load policy
    state = service.load("ppolicy", dn)
    values = state.tabs["main"].values
    assert values["cn"] == "developers"
    assert values["description"] == "Policy for developers"
    assert values["pwdMinLength"] == 12
    assert values["pwdInHistory"] == 5
    assert values["pwdMinAge"] == 1
    assert values["pwdMaxAge"] == 90
    assert values["pwdExpireWarning"] == 14
    assert values["pwdLockoutDuration"] == 1
    assert values["pwdFailureCountInterval"] == 1
    assert values["pwdMustChange"] is True
    assert values["pwdAllowUserChange"] is True
    assert values["pwdSafeModify"] is False
    assert values["pwdLockout"] is True
    assert values["pwdMaxFailure"] == 3
    assert values["pwdCheckQuality"] == "2"

    # 3. Update policy
    service.update(
        "ppolicy",
        dn,
        {
            "main": {
                "values": {
                    "description": "Updated developer policy",
                    "pwdMaxAge": 60,
                    "pwdLockout": False,
                }
            }
        },
    )
    state2 = service.load("ppolicy", dn)
    assert state2.tabs["main"].values["description"] == "Updated developer policy"
    assert state2.tabs["main"].values["pwdMaxAge"] == 60
    assert state2.tabs["main"].values["pwdLockout"] is False
    updated_raw = directory.get(dn)
    assert updated_raw is not None
    assert updated_raw.get("pwdMaxAge") == [b"5184000"]  # 60 * 86400
    assert updated_raw.text("pwdLockout") == "FALSE"
    # 4. List policy
    page = service.list("ppolicy", base=BASE)
    assert any(row.dn == dn for row in page.items)

    # 5. Delete policy
    service.delete("ppolicy", dn)
    with pytest.raises(ObjectNotFoundError):
        service.load("ppolicy", dn)


def test_policy_read_arbitrary_non_whole_seconds(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = f"cn=legacy,{PPOLICIES}"
    directory.add(
        dn,
        {
            "objectClass": [b"device", b"pwdPolicy"],
            "cn": [b"legacy"],
            "pwdAttribute": [b"userPassword"],
            "pwdMinAge": [b"75"],  # 75 seconds, not a multiple of 86400
            "pwdMaxAge": [b"86400"],
        },
    )
    state = service.load("ppolicy", dn)
    assert state.tabs["main"].values["pwdMinAge"] == 75
    assert state.tabs["main"].values["pwdMaxAge"] == 1

    # Update description only; pwdMinAge should remain 75 in LDAP
    service.update("ppolicy", dn, {"main": {"values": {"description": "Legacy policy"}}})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("pwdMinAge") == "75"
    assert entry.text("description") == "Legacy policy"


# ------------------------------------------------------------- pwdPolicyChecker conditional


def test_pwd_policy_checker_not_in_schema(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    # Default MemoryDirectory schema does NOT have pwdPolicyChecker
    assert "pwdpolicychecker" not in directory.schema_object_classes()

    dn = new_policy(service, "no-checker")
    entry = directory.get(dn)
    assert entry is not None
    classes = entry.texts("objectClass")
    assert "device" in classes
    assert "pwdPolicy" in classes
    assert "pwdPolicyChecker" not in classes

    # Without pwdPolicyChecker in the schema the checker tab is not offered at all
    assert service.registry.get("ppolicy").tab("checker") is None
    with pytest.raises(ObjectValidationError):
        service.create(
            "ppolicy",
            BASE,
            {
                "main": {"values": {"cn": "invalid-checker"}},
                "checker": {"active": True, "values": {"pwdCheckModule": "check_module.so"}},
            },
        )


def test_pwd_policy_checker_in_schema(directory: MemoryDirectory) -> None:
    # Add pwdPolicyChecker to schema
    schema = directory.schema_object_classes() | {"pwdPolicyChecker"}
    directory.set_schema_object_classes(schema)

    registry = TypeRegistry()
    register_builtin_types(registry)
    registry.register_plugin(ppolicy.plugin(), {c.lower() for c in schema})
    service = ObjectService(directory, registry)

    dn = service.create(
        "ppolicy",
        BASE,
        {
            "main": {"values": {"cn": "with-checker"}},
            "checker": {"active": True, "values": {"pwdCheckModule": "check_module.so"}},
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    classes = entry.texts("objectClass")
    assert "pwdPolicyChecker" in classes
    assert entry.text("pwdCheckModule") == "check_module.so"
    state = service.load("ppolicy", dn)
    assert state.tabs["checker"].active
    # a policy without the checker class loads with the tab inactive
    plain = service.create("ppolicy", BASE, {"main": {"values": {"cn": "plain"}}})
    assert not service.load("ppolicy", plain).tabs["checker"].active
    # deactivating removes the class and the module
    service.update("ppolicy", dn, {"checker": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert "pwdPolicyChecker" not in entry.texts("objectClass")
    assert not entry.get("pwdCheckModule")


# ------------------------------------------------------------- user tab on user


def test_user_tab_ppolicy_always_active_and_no_deactivation(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(service, "testuser")
    state = service.load("user", dn)

    # ppolicy tab must be active
    assert "ppolicy" in state.tabs
    assert state.tabs["ppolicy"].active is True

    # Check tab descriptor: optional must be False
    desc = service.registry.get("user").tab("ppolicy")
    assert desc is not None
    assert desc.describe()["optional"] is False

    # Deactivation attempt must be rejected
    with pytest.raises(ObjectValidationError) as exc:
        service.update("user", dn, {"ppolicy": {"active": False}})
    assert "ppolicy" in exc.value.fields


def test_user_tab_read_operational_attributes(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    user_dn = new_user(service, "lockeduser")
    # Simulate directory having operational attributes
    directory.modify(
        user_dn,
        [
            Modification("replace", "pwdChangedTime", [b"20261107100000Z"]),
            Modification("replace", "pwdAccountLockedTime", [b"20261107110000Z"]),
            Modification("replace", "pwdFailureTime", [b"20261107105500Z"]),
            Modification("replace", "pwdReset", [b"TRUE"]),
            Modification("replace", "pwdStartTime", [b"20260101000000Z"]),
            Modification("replace", "pwdEndTime", [b"20261231235959Z"]),
            Modification("replace", "pwdPolicySubentry", [b"cn=standard,ou=ppolicies,dc=test"]),
        ],
    )

    state = service.load("user", user_dn)
    pp_values = state.tabs["ppolicy"].values
    assert pp_values["pwdChangedTime"] == datetime(2026, 11, 7, 10, 0, 0, tzinfo=UTC)
    assert pp_values["pwdAccountLockedTime"] == datetime(2026, 11, 7, 11, 0, 0, tzinfo=UTC)
    assert pp_values["pwdFailureTime"] == datetime(2026, 11, 7, 10, 55, 0, tzinfo=UTC)
    assert pp_values["pwdReset"] is True
    assert pp_values["pwdStartTime"] == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert pp_values["pwdEndTime"] == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert pp_values["pwdPolicySubentry"] == "cn=standard,ou=ppolicies,dc=test"

    # Read-only attributes are never written back
    service.update("user", user_dn, {"main": {"values": {"sn": "Smith"}}})
    entry = directory.get(user_dn)
    assert entry is not None
    assert entry.text("pwdAccountLockedTime") == "20261107110000Z"


def test_user_tab_pwd_reset_write(service: ObjectService, directory: MemoryDirectory) -> None:
    user_dn = new_user(service, "resetuser")

    # Set pwdReset = True
    service.update("user", user_dn, {"ppolicy": {"values": {"pwdReset": True}}})
    entry = directory.get(user_dn)
    assert entry is not None
    assert entry.text("pwdReset") == "TRUE"

    state = service.load("user", user_dn)
    assert state.tabs["ppolicy"].values["pwdReset"] is True

    # Set pwdReset = False
    service.update("user", user_dn, {"ppolicy": {"values": {"pwdReset": False}}})
    entry2 = directory.get(user_dn)
    assert entry2 is not None
    assert entry2.text("pwdReset") == "FALSE"

    state2 = service.load("user", user_dn)
    assert state2.tabs["ppolicy"].values["pwdReset"] is False


# ------------------------------------------------------------- account unlock hook


def test_account_unlock_hook() -> None:
    # Locked entry with pwdAccountLockedTime
    entry_locked = MemoryDirectory.from_ldif("""dn: uid=locked,ou=people,dc=test
objectClass: inetOrgPerson
uid: locked
cn: Locked User
sn: User
pwdAccountLockedTime: 20261107120000Z
""").get("uid=locked,ou=people,dc=test")
    assert entry_locked is not None

    # Locking an account does not change pwdAccountLockedTime
    mods_lock = unlock_account_hook(entry_locked, locked=True)
    assert mods_lock == []

    # Unlocking an account deletes pwdAccountLockedTime
    mods_unlock = unlock_account_hook(entry_locked, locked=False)
    assert mods_unlock == [Modification("delete", "pwdAccountLockedTime")]

    # Entry without pwdAccountLockedTime
    entry_unlocked = MemoryDirectory.from_ldif("""dn: uid=unlocked,ou=people,dc=test
objectClass: inetOrgPerson
uid: unlocked
cn: Unlocked User
sn: User
""").get("uid=unlocked,ou=people,dc=test")
    assert entry_unlocked is not None

    mods_unlock_noop = unlock_account_hook(entry_unlocked, locked=False)
    assert mods_unlock_noop == []


# ------------------------------------------------------------- default policy hint


def test_plugin_settings_are_registered() -> None:
    settings = PpolicySettings(default_policy_dn="cn=default,ou=ppolicies,dc=test")
    registry = TypeRegistry()
    register_builtin_types(registry)
    registry.register_plugin(ppolicy.plugin(settings), {"pwdpolicy", "device"})
    assert registry.settings["ppolicy"] is settings
    assert "default policy" in PwdPolicySubentryAttr().description
