"""Automatic groups plugin: rules, add/remove, group kinds, schedule, CRUD."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import heracles_plugins.automatic_groups as ag
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.automatic_groups.runner import ForbiddenAttributeError

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
TASKS = f"ou=tasks,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
TASK_DN = f"cn=auto,{TASKS}"
GROUP = f"cn=staff,{GROUPS}"
UNIX_GROUP = f"cn=unix,{GROUPS}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes([*d.schema_object_classes(), "hrcTasksAutomaticGroups"])
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for dn, ou in ((PEOPLE, "people"), (GROUPS, "groups"), (TASKS, "tasks")):
        d.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    return d


def add_user(d: MemoryDirectory, uid: str, **extra: str) -> str:
    dn = f"uid={uid},{PEOPLE}"
    attrs = {
        "objectClass": [b"inetOrgPerson"],
        "uid": [uid.encode()],
        "cn": [uid.encode()],
        "sn": [b"X"],
    }
    attrs.update({k: [v.encode() for v in v_.split("|")] for k, v_ in extra.items()})
    d.add(dn, attrs)
    return dn


def add_group(d: MemoryDirectory, members: list[str]) -> None:
    d.add(
        GROUP,
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"staff"],
            "member": [m.encode() for m in members],
        },
    )


def add_task(
    d: MemoryDirectory,
    members: list[str],
    pattern: str | None,
    dynamic: bool = False,
    group: str = GROUP,
) -> None:
    attrs: dict[str, list[bytes]] = {
        "objectClass": [b"hrcTasks", b"hrcTasksAutomaticGroups"],
        "cn": [b"auto"],
        "hrcTasksStatus": [b"Activated"],
        "hrcTasksRepeatable": [b"TRUE"],
        "hrcTasksRepeatableSchedule": [b"daily"],
        "hrcTasksAutomaticGroupsOfName": [group.encode()],
        "hrcTasksAutomaticGroupsMembers": [m.encode() for m in members],
        "hrcTasksAutomaticGroupsDynamicGroup": [b"TRUE" if dynamic else b"FALSE"],
    }
    if pattern is not None:
        attrs["hrcTasksAutomaticGroupsRegexPattern"] = [pattern.encode()]
    d.add(TASK_DN, attrs)


def members(d: MemoryDirectory, dn: str = GROUP, attr: str = "member") -> list[str]:
    e = d.get(dn)
    assert e is not None
    return sorted(e.texts(attr))


def test_matching_users_are_added_others_left(directory: MemoryDirectory) -> None:
    a = add_user(directory, "stu-a")
    b = add_user(directory, "stu-b")
    c = add_user(directory, "other")
    seed = add_user(directory, "seed")
    add_group(directory, [seed])
    add_task(directory, [a, b, c], "^stu-")
    report = ag.run_automatic_groups(directory, NOW)
    assert members(directory) == sorted([seed, a, b])
    assert report.changes[0].added == (a, b) and report.changes[0].removed == ()
    assert report.tasks_run == 1
    # second pass (after the schedule): nothing to change
    again = ag.run_automatic_groups(directory, NOW + timedelta(days=1, minutes=1))
    assert again.tasks_run == 1 and again.changes == []


def test_attribute_prefixed_rule(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", mail="a@example.com")
    b = add_user(directory, "b", mail="b@other.org")
    seed = add_user(directory, "seed")
    add_group(directory, [seed])
    add_task(directory, [a, b], r"mail:@example\.com$")
    ag.run_automatic_groups(directory, NOW)
    assert members(directory) == sorted([seed, a])


def test_default_attribute_setting_and_empty_pattern_matches_everyone(
    directory: MemoryDirectory,
) -> None:
    a = add_user(directory, "a")
    b = add_user(directory, "b")
    add_group(directory, [a])
    add_task(directory, [a, b], None)
    ag.run_automatic_groups(directory, NOW)
    assert members(directory) == sorted([a, b])
    assert ag.parse_rule("x", "cn")[0] == "cn"
    assert ag.parse_rule("sn:x", "cn")[0] == "sn"
    assert ag.parse_rule("(?:x)", "cn")[0] == "cn"


def test_dynamic_group_removes_users_who_no_longer_match(directory: MemoryDirectory) -> None:
    keep = add_user(directory, "stu-keep")
    left = add_user(directory, "left")
    outsider = add_user(directory, "outsider")  # not a member of the task: untouched
    add_group(directory, [keep, left, outsider])
    add_task(directory, [keep, left], "^stu-", dynamic=True)
    report = ag.run_automatic_groups(directory, NOW)
    assert members(directory) == sorted([keep, outsider])
    assert report.changes[0].removed == (left,)


def test_group_is_never_emptied(directory: MemoryDirectory) -> None:
    left = add_user(directory, "left")
    add_group(directory, [left])
    add_task(directory, [left], "^stu-", dynamic=True)
    report = ag.run_automatic_groups(directory, NOW)
    assert members(directory) == [left]
    assert "at least one member" in report.errors[0]


def test_posix_group_uses_member_uid(directory: MemoryDirectory) -> None:
    a = add_user(directory, "stu-a")
    b = add_user(directory, "gone")
    directory.add(
        UNIX_GROUP,
        {
            "objectClass": [b"posixGroup"],
            "cn": [b"unix"],
            "gidNumber": [b"2000"],
            "memberUid": [b"gone", b"seed"],
        },
    )
    add_task(directory, [a, b], "^stu-", dynamic=True, group=UNIX_GROUP)
    ag.run_automatic_groups(directory, NOW)
    assert members(directory, UNIX_GROUP, "memberUid") == ["seed", "stu-a"]


def test_groups_and_roles_expanded(directory: MemoryDirectory) -> None:
    a = add_user(directory, "stu-a")
    directory.add(
        f"cn=src,{GROUPS}",
        {"objectClass": [b"groupOfNames"], "cn": [b"src"], "member": [a.encode()]},
    )
    seed = add_user(directory, "seed")
    add_group(directory, [seed])
    add_task(directory, [f"cn=src,{GROUPS}"], "^stu-")
    ag.run_automatic_groups(directory, NOW)
    assert members(directory) == sorted([seed, a])


def test_missing_group_and_invalid_rule_keep_the_task(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a")
    add_task(directory, [a], "^a")
    report = ag.run_automatic_groups(directory, NOW)
    assert report.tasks_run == 0 and "group not found" in report.errors[0]
    directory.delete(TASK_DN)
    add_group(directory, [a])
    add_task(directory, [a], "(")
    report = ag.run_automatic_groups(directory, NOW)
    assert report.tasks_run == 0 and "invalid rule" in report.errors[0]
    entry: Entry | None = directory.get(TASK_DN)
    assert entry is not None and entry.text("hrcTasksStatus") == "Activated"


def test_task_type_and_validation(directory: MemoryDirectory) -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    assert registry.register_plugin(
        ag.plugin(), {c.lower() for c in directory.schema_object_classes()}
    ).enabled
    info = registry.get("automatic_groups_task")
    assert info.acl_object(info.main_tab) == "tasks/automaticGroupsTask"
    assert info.type.filter == "(&(objectClass=hrcTasks)(objectClass=hrcTasksAutomaticGroups))"
    a = add_user(directory, "a")
    add_group(directory, [a])
    service = ObjectService(directory, registry)
    values = {
        "cn": "auto",
        "hrcTasksAutomaticGroupsOfName": GROUP,
        "hrcTasksAutomaticGroupsMembers": [a],
        "hrcTasksAutomaticGroupsRegexPattern": "mail:@x$",
        "hrcTasksAutomaticGroupsDynamicGroup": True,
    }
    dn = service.create("automatic_groups_task", BASE, {"main": {"values": values}})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("hrcTasksAutomaticGroupsDynamicGroup") == "TRUE"
    with pytest.raises(ObjectValidationError):
        service.update(
            "automatic_groups_task",
            dn,
            {"main": {"values": {"hrcTasksAutomaticGroupsRegexPattern": "("}}},
        )
    with pytest.raises(ObjectValidationError):
        service.create(
            "automatic_groups_task",
            BASE,
            {"main": {"values": {**values, "cn": "other", "hrcTasksAutomaticGroupsOfName": None}}},
        )


def test_a_rule_cannot_test_secret_attributes(directory: MemoryDirectory) -> None:
    # The membership it produces would be an oracle on password hashes.
    for rule in ("userPassword:^\\{SSHA\\}ab", "sambaNTPassword:^A"):
        with pytest.raises(ForbiddenAttributeError):
            ag.parse_rule(rule, "uid")
    a = add_user(directory, "a", userPassword="{SSHA}abc")
    add_group(directory, [a])
    add_task(directory, [a], "userPassword:^\\{SSHA\\}ab")
    report = ag.run_automatic_groups(directory, NOW)
    assert report.tasks_run == 0 and "cannot test userPassword" in report.errors[0]
    assert members(directory) == [a]
