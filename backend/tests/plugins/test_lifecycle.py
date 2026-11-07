"""Lifecycle plugin: end date detection, actions (lock, move, set attribute), schedule, CRUD."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import heracles_plugins.lifecycle as lc
from heracles.auth.passwords import is_locked
from heracles.ldap.client import Entry, Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
TASKS = f"ou=tasks,{BASE}"
ARCHIVED = f"ou=alumni,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
TODAY = NOW.date()
EPOCH = date(1970, 1, 1)
TASK_DN = f"cn=ends,{TASKS}"


def days(d: date) -> str:
    return str((d - EPOCH).days)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes([*d.schema_object_classes(), "fdTasksLifeCycle"])
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for dn, ou in ((PEOPLE, "people"), (GROUPS, "groups"), (TASKS, "tasks")):
        d.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.add(ARCHIVED, {"objectClass": [b"organizationalUnit"], "ou": [b"alumni"]})
    return d


def add_user(d: MemoryDirectory, uid: str, end: date | None, **extra: str) -> str:
    dn = f"uid={uid},{PEOPLE}"
    attrs = {
        "objectClass": [b"inetOrgPerson", b"posixAccount", b"shadowAccount"],
        "uid": [uid.encode()],
        "cn": [uid.encode()],
        "sn": [b"X"],
        "userPassword": [b"{SSHA}abcdef"],
    }
    if end is not None:
        attrs["shadowExpire"] = [days(end).encode()]
    attrs.update({k: [v.encode()] for k, v in extra.items()})
    d.add(dn, attrs)
    return dn


def add_task(d: MemoryDirectory, members: list[str], **extra: str) -> None:
    attrs: dict[str, list[bytes]] = {
        "objectClass": [b"fdTasks", b"fdTasksLifeCycle"],
        "cn": [b"ends"],
        "fdTasksStatus": [b"Activated"],
        "fdTasksRepeatable": [b"TRUE"],
        "fdTasksRepeatableSchedule": [b"daily"],
        "fdTasksLifeCycleMembers": [m.encode() for m in members],
    }
    attrs.update({k: [v.encode()] for k, v in extra.items()})
    d.add(TASK_DN, attrs)


def entry(d: MemoryDirectory, dn: str) -> Entry:
    e = d.get(dn)
    assert e is not None
    return e


def test_lock_accounts_that_reached_their_end_date(directory: MemoryDirectory) -> None:
    gone = add_user(directory, "gone", TODAY - timedelta(days=3))
    today = add_user(directory, "today", TODAY)
    future = add_user(directory, "future", TODAY + timedelta(days=1))
    none = add_user(directory, "noend", None)
    add_task(directory, [gone, today, future, none])
    report = lc.run_lifecycle(directory, NOW)
    assert sorted(r.user_dn for r in report.accounts) == sorted([gone, today])
    assert all(r.changes == ("lock",) for r in report.accounts)
    assert is_locked(entry(directory, gone).text("userPassword") or "")
    assert is_locked(entry(directory, today).text("userPassword") or "")
    assert not is_locked(entry(directory, future).text("userPassword") or "")
    assert not is_locked(entry(directory, none).text("userPassword") or "")
    assert report.tasks_run == 1


def test_run_is_idempotent_and_task_rescheduled(directory: MemoryDirectory) -> None:
    gone = add_user(directory, "gone", TODAY - timedelta(days=3))
    add_task(directory, [gone])
    assert lc.run_lifecycle(directory, NOW).tasks_run == 1
    assert lc.run_lifecycle(directory, NOW).tasks_run == 0
    later = lc.run_lifecycle(directory, NOW + timedelta(days=2))
    assert later.tasks_run == 1 and later.accounts == []  # already locked: nothing to report


def test_grace_period_and_login_pattern(directory: MemoryDirectory) -> None:
    a = add_user(directory, "stu-a", TODAY - timedelta(days=5))
    b = add_user(directory, "stu-b", TODAY - timedelta(days=20))
    c = add_user(directory, "staff-c", TODAY - timedelta(days=20))
    add_task(
        directory,
        [a, b, c],
        fdTasksLifeCyclePostEndDate="10",
        fdTasksLifeCycleRegexPattern="^stu-",
    )
    report = lc.run_lifecycle(directory, NOW)
    assert [r.user_dn for r in report.accounts] == [b]


def test_groups_and_roles_are_expanded(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", TODAY - timedelta(days=1))
    directory.add(
        f"cn=g,{GROUPS}",
        {"objectClass": [b"groupOfNames"], "cn": [b"g"], "member": [a.encode()]},
    )
    add_task(directory, [f"cn=g,{GROUPS}"])
    assert [r.user_dn for r in lc.run_lifecycle(directory, NOW).accounts] == [a]


def test_move_to_department(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", TODAY - timedelta(days=1))
    add_task(directory, [a])
    settings = lc.LifecycleSettings(action="move", target_department=ARCHIVED)
    report = lc.run_lifecycle(directory, NOW, settings)
    new_dn = f"uid=a,ou=people,{ARCHIVED}"
    assert report.accounts[0].changes == ("move",)
    assert report.accounts[0].new_dn == new_dn
    assert directory.get(a) is None and directory.get(new_dn) is not None
    # the old DN of the member is gone: a later run finds nothing to do
    assert lc.run_lifecycle(directory, NOW + timedelta(days=2), settings).accounts == []


def test_set_attribute_and_closure_lock(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", TODAY - timedelta(days=1), employeeType="staff")
    add_task(directory, [a], fdTasksLifeCycleEnableAccountClosure="TRUE")
    settings = lc.LifecycleSettings(
        action="set_attribute", attribute="employeeType", value="alumni"
    )
    report = lc.run_lifecycle(directory, NOW, settings)
    assert report.accounts[0].changes == ("lock", "set:employeeType")
    e = entry(directory, a)
    assert e.text("employeeType") == "alumni" and is_locked(e.text("userPassword") or "")


def test_lock_hooks_run(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", TODAY - timedelta(days=1), description="open")

    def hook(user: Entry, locked: bool) -> list[Modification]:
        return [Modification("replace", "description", [b"locked" if locked else b"open"])]

    add_task(directory, [a])
    lc.run_lifecycle(directory, NOW, lock_hooks=[hook])
    assert entry(directory, a).text("description") == "locked"


def test_end_date_attribute_as_generalized_time(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", None, departureDate="20300601000000Z")
    b = add_user(directory, "b", None, departureDate="20300701000000Z")
    add_task(directory, [a, b])
    settings = lc.LifecycleSettings(end_date_attribute="departureDate")
    assert [r.user_dn for r in lc.run_lifecycle(directory, NOW, settings).accounts] == [a]


def test_invalid_pattern_task_is_reported_and_kept(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", TODAY - timedelta(days=1))
    add_task(directory, [a], fdTasksLifeCycleRegexPattern="(")
    report = lc.run_lifecycle(directory, NOW)
    assert report.tasks_run == 0 and report.errors and report.accounts == []


def test_deactivated_task_and_missing_container() -> None:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    assert lc.run_lifecycle(d, NOW).tasks_examined == 0


def test_task_type_and_validation(directory: MemoryDirectory) -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    assert registry.register_plugin(
        lc.plugin(), {c.lower() for c in directory.schema_object_classes()}
    ).enabled
    info = registry.get("lifecycle_task")
    assert info.acl_object(info.main_tab) == "tasks/lifeCycleTask"
    assert info.type.filter == "(&(objectClass=fdTasks)(objectClass=fdTasksLifeCycle))"
    a = add_user(directory, "a", None)
    service = ObjectService(directory, registry)
    dn = service.create(
        "lifecycle_task",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "ends",
                    "fdTasksLifeCycleMembers": [a],
                    "fdTasksLifeCyclePostEndDate": 7,
                    "fdTasksLifeCycleRegexPattern": "^stu",
                    "fdTasksLifeCycleEnableAccountClosure": True,
                }
            }
        },
    )
    assert dn == TASK_DN
    e = entry(directory, dn)
    assert e.text("fdTasksLifeCyclePostEndDate") == "7"
    assert e.text("fdTasksLifeCycleEnableAccountClosure") == "TRUE"
    with pytest.raises(ObjectValidationError):
        service.update(
            "lifecycle_task", dn, {"main": {"values": {"fdTasksLifeCycleRegexPattern": "("}}}
        )
    with pytest.raises(ObjectValidationError):
        service.create("lifecycle_task", BASE, {"main": {"values": {"cn": "nomembers"}}})


def test_plugin_disabled_without_schema() -> None:
    registry = TypeRegistry()
    assert not registry.register_plugin(lc.plugin(), {"fdtasks"}).enabled
