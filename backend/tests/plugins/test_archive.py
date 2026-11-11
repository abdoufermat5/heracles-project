"""Archive plugin: archiving, unique key lookup, purge task, before-delete events, types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import heracles_plugins.archive as archive
from heracles.ldap.client import NoSuchObjectError
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.archive.service import ARCHIVE_CLASS

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
ARCH = f"ou=archive,{BASE}"
TASKS = f"ou=tasks,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
JDOE = f"uid=jdoe,{PEOPLE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes([*d.schema_object_classes(), ARCHIVE_CLASS, "hrcArchiveTasks"])
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(
        JDOE,
        {
            "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
            "uid": [b"jdoe"],
            "cn": [b"John Doe"],
            "givenName": [b"John"],
            "sn": [b"Doe"],
            "mail": [b"jdoe@example.com", b"john@example.com"],
            "userPassword": [b"{SSHA}secret"],
            "jpegPhoto": [b"\xff\xd8\xff"],
        },
    )
    return d


def make_registry(directory: MemoryDirectory) -> TypeRegistry:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        archive.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return registry


def attrs_of(directory: MemoryDirectory, dn: str) -> dict[str, list[str]]:
    entry = directory.get(dn)
    assert entry is not None
    return {k: [v.decode() for v in vs] for k, vs in entry.attrs.items()}


def test_archive_keeps_selected_attributes_and_unique_key(directory: MemoryDirectory) -> None:
    dn = archive.archive(directory, JDOE, "user", now=NOW)
    assert dn == f"cn=user_jdoe_20300615080000,{ARCH}"
    a = attrs_of(directory, dn)
    assert a["objectClass"] == [ARCHIVE_CLASS]
    assert a["hrcArchivedObjectType"] == ["user"]
    assert a["hrcArchivedOriginDn"] == [JDOE]
    assert a["hrcArchivedDateTime"] == ["20300615080000Z"]
    assert a["hrcArchivedUniqueField"] == ["uid=jdoe"]
    assert "mail=jdoe@example.com" in a["hrcArchivedField"]
    assert "mail=john@example.com" in a["hrcArchivedField"]
    assert "sn=Doe" in a["hrcArchivedField"]
    joined = " ".join(a["hrcArchivedField"])
    assert "userPassword" not in joined and "jpegPhoto" not in joined
    assert directory.get(JDOE) is not None  # the object stays


def test_archive_twice_gets_distinct_entries_and_is_found_by_unique_key(
    directory: MemoryDirectory,
) -> None:
    first = archive.archive(directory, JDOE, "user", now=NOW)
    second = archive.archive(directory, JDOE, "user", now=NOW)
    later = archive.archive(directory, JDOE, "user", now=NOW + timedelta(days=1))
    assert len({first, second, later}) == 3
    found = archive.find_archives(directory, "user", {"uid": "jdoe"})
    assert found[0].dn == later
    assert len(found) == 3
    assert archive.find_archives(directory, "user", {"uid": "other"}) == []
    assert archive.find_archives(directory, "group", {"uid": "jdoe"}) == []


def test_archive_errors(directory: MemoryDirectory) -> None:
    with pytest.raises(archive.ArchiveError):
        archive.archive(directory, JDOE, "printer")
    with pytest.raises(NoSuchObjectError):
        archive.archive(directory, f"uid=ghost,{PEOPLE}", "user")
    directory.add(
        f"cn=nologin,{PEOPLE}",
        {"objectClass": [b"inetOrgPerson"], "cn": [b"x"], "sn": [b"x"]},
    )
    with pytest.raises(archive.ArchiveError):
        archive.archive(directory, f"cn=nologin,{PEOPLE}", "user")


def test_custom_rules_and_unsafe_key_characters(directory: MemoryDirectory) -> None:
    directory.add(
        f"cn=we ird/name,{BASE}",
        {"objectClass": [b"groupOfNames"], "cn": [b"we ird/name"], "member": [JDOE.encode()]},
    )
    settings = archive.ArchiveSettings(
        rules={"group": archive.ArchiveRule(fields=("cn",), unique_fields=("cn",))}
    )
    dn = archive.archive(directory, f"cn=we ird/name,{BASE}", "group", settings=settings, now=NOW)
    assert dn == f"cn=group_we_ird_name_20300615080000,{ARCH}"
    assert attrs_of(directory, dn)["hrcArchivedField"] == ["cn=we ird/name"]


def test_before_delete_event_archives_then_deletes(directory: MemoryDirectory) -> None:
    registry = make_registry(directory)
    service = ObjectService(directory, registry, events=archive.ArchiveBeforeDelete(directory))
    service.delete("user", JDOE)
    assert directory.get(JDOE) is None
    assert len(archive.find_archives(directory, "user", {"uid": "jdoe"})) == 1


def test_purge_task(directory: MemoryDirectory) -> None:
    for days in (3000, 1000):
        archive.archive(directory, JDOE, "user", now=NOW - timedelta(days=days))
    directory.add(TASKS, {"objectClass": [b"organizationalUnit"], "ou": [b"tasks"]})
    task = f"cn=purge,{TASKS}"
    directory.add(
        task,
        {
            "objectClass": [b"hrcTasks", b"hrcArchiveTasks"],
            "cn": [b"purge"],
            "hrcTasksStatus": [b"Activated"],
            "hrcTasksRepeatable": [b"TRUE"],
            "hrcTasksRepeatableSchedule": [b"weekly"],
        },
    )
    report = archive.run_archive(directory, NOW, archive.ArchiveSettings(retention_days=1825))
    assert report.archives_purged == 1 and report.tasks_run == 1
    assert len(archive.find_archives(directory, "user", {"uid": "jdoe"})) == 1
    assert archive.run_archive(directory, NOW).tasks_run == 0  # rescheduled
    again = archive.run_archive(directory, NOW + timedelta(days=8))
    assert again.archives_purged == 0 and again.tasks_run == 1


def test_purge_disabled_with_zero_retention(directory: MemoryDirectory) -> None:
    archive.archive(directory, JDOE, "user", now=NOW - timedelta(days=9000))
    directory.add(TASKS, {"objectClass": [b"organizationalUnit"], "ou": [b"tasks"]})
    directory.add(
        f"cn=purge,{TASKS}",
        {
            "objectClass": [b"hrcTasks", b"hrcArchiveTasks"],
            "cn": [b"purge"],
            "hrcTasksStatus": [b"Activated"],
        },
    )
    report = archive.run_archive(directory, NOW, archive.ArchiveSettings(retention_days=0))
    assert report.archives_purged == 0 and report.tasks_run == 1


def test_plugin_disabled_without_schema() -> None:
    registry = TypeRegistry()
    status = registry.register_plugin(archive.plugin(), set())
    assert not status.enabled


def test_types_acl_keys_and_read_only(directory: MemoryDirectory) -> None:
    registry = make_registry(directory)
    task = registry.get("archive_task")
    assert task.acl_object(task.main_tab) == "tasks/archiveTask"
    assert task.type.filter == "(&(objectClass=hrcTasks)(objectClass=hrcArchiveTasks))"
    obj = registry.get("archived_object")
    assert obj.acl_object(obj.main_tab) == "archivedObject/archivedObject"
    assert obj.type.rdn == "ou=archive"
    service = ObjectService(directory, registry)
    dn = archive.archive(directory, JDOE, "user", now=NOW)
    state = service.load("archived_object", dn)
    assert state.tabs["main"].values["hrcArchivedObjectType"] == "user"
    with pytest.raises(ObjectValidationError):
        service.update(
            "archived_object", dn, {"main": {"values": {"hrcArchivedObjectType": "group"}}}
        )
    page = service.list("archived_object")
    assert page.total == 1


def test_archive_task_crud(directory: MemoryDirectory) -> None:
    service = ObjectService(directory, make_registry(directory))
    dn = service.create(
        "archive_task", BASE, {"main": {"values": {"cn": "purge", "hrcTasksRepeatable": False}}}
    )
    assert dn == f"cn=purge,{TASKS}"
    entry = directory.get(dn)
    assert entry is not None and entry.has_object_class("hrcArchiveTasks")


def test_archive_respects_read_acl(directory: MemoryDirectory) -> None:
    dn = archive.archive(directory, JDOE, "user", now=NOW, can_read=lambda a: a != "mail")
    fields = attrs_of(directory, dn)["hrcArchivedField"]
    assert not any(f.startswith("mail=") for f in fields)
    assert "sn=Doe" in fields
    with pytest.raises(archive.ArchiveError):
        archive.archive(directory, JDOE, "user", now=NOW, can_read=lambda a: a != "uid")
