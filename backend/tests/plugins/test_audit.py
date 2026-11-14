"""Audit plugin: event recording, purge task, syslog forwarding, security tab, types."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

import heracles_plugins.audit as audit
from heracles.core.generalized_time import format_generalized_time
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import (
    ObjectService,
    ObjectValidationError,
    PermissionDeniedError,
    TypeRegistry,
)
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.audit.events import write_event
from heracles_plugins.audit.router import AuditQuery, page_events

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
AUDIT = f"ou=audit,{BASE}"
TASKS = f"ou=tasks,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
ADMIN = f"uid=admin,{PEOPLE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes([*d.schema_object_classes(), "hrcAuditEvent", "hrcAuditTasks"])
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


def make_registry(directory: MemoryDirectory) -> TypeRegistry:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        audit.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return registry


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = make_registry(directory)
    events = audit.AuditEvents(directory, author_dn=ADMIN, author_ip="10.1.2.3")
    return ObjectService(directory, registry, events=events)


def events(directory: MemoryDirectory) -> list[dict[str, list[str]]]:
    found = directory.search(AUDIT, "(objectClass=hrcAuditEvent)")
    return sorted(
        ({k: [v.decode() for v in vs] for k, vs in e.attrs.items()} for e in found),
        key=lambda e: e["hrcAuditAction"],
    )


def add_task(directory: MemoryDirectory, **extra: str) -> str:
    if directory.get(TASKS) is None:
        directory.add(TASKS, {"objectClass": [b"organizationalUnit"], "ou": [b"tasks"]})
    attrs = {
        "objectClass": [b"hrcTasks", b"hrcAuditTasks"],
        "cn": [b"purge"],
        "hrcTasksStatus": [b"Activated"],
        "hrcTasksRepeatable": [b"TRUE"],
        "hrcTasksRepeatableSchedule": [b"daily"],
    }
    attrs.update({k: [v.encode()] for k, v in extra.items()})
    dn = f"cn=purge,{TASKS}"
    directory.add(dn, attrs)
    return dn


# ------------------------------------------------------------------ events


def test_create_modify_delete_are_recorded(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "user", BASE, {"main": {"values": {"uid": "jdoe", "givenName": "J", "sn": "Doe"}}}
    )
    service.update("user", dn, {"main": {"values": {"mail": "j@example.com"}}})
    service.delete("user", dn)
    found = events(directory)
    assert [e["hrcAuditAction"][0] for e in found] == ["create", "delete", "modify"]
    create, delete, modify = found
    assert create["hrcAuditObject"] == [dn]
    assert create["hrcAuditObjectType"] == ["user"]
    assert create["hrcAuditAuthorDN"] == [ADMIN]
    assert create["hrcAuditAuthorIP"] == ["10.1.2.3"]
    assert create["hrcAuditResult"] == ["success"]
    assert "uid: jdoe" in create["hrcAuditAttributes"]
    assert "hrcAuditAttributes" not in delete
    assert modify["hrcAuditAttributes"] == ["replace mail: j@example.com"]
    assert all(e["objectClass"] == ["hrcAuditEvent"] for e in found)
    assert all(len(e["hrcAuditDateTime"][0]) == 15 for e in found)


def test_hidden_values_and_actions_filter(directory: MemoryDirectory) -> None:
    registry = make_registry(directory)
    settings = audit.AuditSettings(actions=("create",), hidden_attributes=("mail",))
    svc = ObjectService(
        directory, registry, events=audit.AuditEvents(directory, ADMIN, settings=settings)
    )
    dn = svc.create(
        "user",
        BASE,
        {
            "main": {
                "values": {"uid": "a", "givenName": "A", "sn": "B", "mail": "s3cret@example.com"}
            }
        },
    )
    svc.delete("user", dn)
    found = events(directory)
    assert len(found) == 1
    attrs = found[0]["hrcAuditAttributes"]
    assert "mail: ***" in attrs
    assert not any("s3cret" in a for a in attrs)


def test_secret_looking_attributes_are_never_logged_whatever_the_settings() -> None:
    from heracles_plugins.audit.events import describe_values

    for name in (
        "hrcSmbNTPassword",
        "hrcIpmiPassword",
        "hrcGroupwareServerPassword",
        "krbPrincipalKey",
    ):
        line = describe_values(name, [b"31D6CFE0D16AE931B73C59D7E0C089C0"], ())
        assert line == f"{name}: ***"
    assert describe_values("userPassword;binary", [b"x"], ("userPassword",)) == (
        "userPassword;binary: ***"
    )
    assert describe_values("description", [b"hello"], ()) == "description: hello"


def test_audit_failure_does_not_break_the_operation(
    service: ObjectService, directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heracles.ldap.client import DirectoryError
    from heracles_plugins.audit import events as ev

    def boom(*_a: object, **_k: object) -> str:
        raise DirectoryError("down")

    monkeypatch.setattr(ev, "write_event", boom)
    dn = service.create(
        "user", BASE, {"main": {"values": {"uid": "x", "givenName": "X", "sn": "Y"}}}
    )
    assert directory.get(dn) is not None


def test_events_of_audit_type_are_not_audited(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    audit_dn = write_event(
        directory, action="create", object_type="user", object_dn="uid=z", author_dn=ADMIN
    )
    with pytest.raises(PermissionDeniedError):
        service.delete("audit_event", audit_dn)
    assert [e["hrcAuditAction"] for e in events(directory)] == [["create"]]


# ------------------------------------------------------------------ runner


def test_purge_old_events_default_and_task_retention(directory: MemoryDirectory) -> None:
    add_task(directory)
    for days in (400, 100, 1):
        write_event(
            directory,
            action="modify",
            object_type="user",
            object_dn=f"uid=u{days},{PEOPLE}",
            author_dn=ADMIN,
            now=NOW - timedelta(days=days),
        )
    report = audit.run_audit(directory, NOW, audit.AuditSettings(retention_days=365))
    assert report.events_purged == 1
    assert report.tasks_run == 1
    assert len(events(directory)) == 2


def test_task_retention_overrides_setting_and_zero_keeps(directory: MemoryDirectory) -> None:
    dn = add_task(directory, hrcAuditTasksRetention="30")
    write_event(
        directory,
        action="create",
        object_type="user",
        object_dn="uid=a",
        author_dn=ADMIN,
        now=NOW - timedelta(days=40),
    )
    assert audit.run_audit(directory, NOW).events_purged == 1
    directory.delete(dn)
    add_task(directory, hrcAuditTasksRetention="0")
    write_event(
        directory,
        action="create",
        object_type="user",
        object_dn="uid=a",
        author_dn=ADMIN,
        now=NOW - timedelta(days=4000),
    )
    assert audit.run_audit(directory, NOW).events_purged == 0


def test_run_is_not_repeated_before_next_execution(directory: MemoryDirectory) -> None:
    add_task(directory)
    assert audit.run_audit(directory, NOW).tasks_run == 1
    assert audit.run_audit(directory, NOW).tasks_run == 0
    assert audit.run_audit(directory, NOW + timedelta(days=1, minutes=1)).tasks_run == 1


def test_runner_without_containers(directory: MemoryDirectory) -> None:
    assert audit.run_audit(directory, NOW).tasks_examined == 0
    add_task(directory)
    assert audit.run_audit(directory, NOW).events_purged == 0


def test_syslog_forwarding(directory: MemoryDirectory, caplog: pytest.LogCaptureFixture) -> None:
    add_task(
        directory,
        hrcAuditSyslogEnabled="TRUE",
        hrcAuditSyslogPrefix="[heracles] ",
        hrcTasksLastExec=format_generalized_time(NOW - timedelta(hours=1)),
    )
    for minutes, obj in ((120, "old"), (30, "recent")):
        write_event(
            directory,
            action="modify",
            object_type="user",
            object_dn=f"uid={obj}",
            author_dn=ADMIN,
            now=NOW - timedelta(minutes=minutes),
        )
    with caplog.at_level(logging.INFO, logger="heracles.audit"):
        report = audit.run_audit(directory, NOW)
    assert report.events_forwarded == 1
    messages = [r.getMessage() for r in caplog.records if r.name == "heracles.audit"]
    assert len(messages) == 1 and messages[0].startswith("[heracles] ")
    assert "uid=recent" in messages[0]


# --------------------------------------------------------- types and tab


def test_plugin_disabled_without_schema() -> None:
    registry = TypeRegistry()
    status = registry.register_plugin(audit.plugin(), set())
    assert not status.enabled and status.missing_object_classes == ["hrcAuditEvent"]


def test_acl_keys_and_containers(directory: MemoryDirectory) -> None:
    registry = make_registry(directory)
    task = registry.get("audit_task")
    assert task.acl_object(task.main_tab) == "tasks/auditTask"
    assert task.type.rdn == "ou=tasks" and task.type.category == "workflow"
    assert task.type.filter == "(&(objectClass=hrcTasks)(objectClass=hrcAuditTasks))"
    event = registry.get("audit_event")
    assert event.acl_object(event.main_tab) == "auditEvent/auditEvent"
    assert event.type.rdn == "ou=audit"
    assert registry.get("user").tab("auditSecurity") is None
    assert not (event.type.creatable or event.type.editable or event.type.deletable)


def test_audit_task_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "audit_task",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "purge",
                    "hrcAuditTasksRetention": 90,
                    "hrcAuditSyslogEnabled": True,
                    "hrcAuditSyslogPrefix": "hrc ",
                }
            }
        },
    )
    assert dn == f"cn=purge,{TASKS}"
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("hrcTasks") and entry.has_object_class("hrcAuditTasks")
    assert entry.text("hrcAuditTasksRetention") == "90"
    assert entry.text("hrcAuditSyslogEnabled") == "TRUE"
    with pytest.raises(ObjectValidationError):
        service.create(
            "audit_task",
            BASE,
            {"main": {"values": {"cn": "bad", "hrcTasksRepeatable": True}}},
        )


def test_audit_events_are_read_only_in_the_object_layer(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = write_event(
        directory,
        action="create",
        object_type="user",
        object_dn="uid=a",
        author_dn=ADMIN,
        attributes=["uid: a"],
    )
    state = service.load("audit_event", dn)
    values = state.tabs["main"].values
    assert values["hrcAuditAction"] == "create"
    assert values["hrcAuditAttributes"] == ["uid: a"]
    with pytest.raises(PermissionDeniedError):
        service.update("audit_event", dn, {"main": {"values": {"hrcAuditResult": "failure"}}})
    with pytest.raises(PermissionDeniedError):
        service.create("audit_event", BASE, {"main": {"values": {"cn": "x"}}})
    with pytest.raises(PermissionDeniedError):
        service.delete("audit_event", dn)


def test_events_for_lists_events_about_and_by_the_user(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "user", BASE, {"main": {"values": {"uid": "jdoe", "givenName": "J", "sn": "Doe"}}}
    )
    service.update("user", dn, {"main": {"values": {"mail": "j@example.com"}}})
    write_event(
        directory, action="modify", object_type="group", object_dn=f"cn=g,{BASE}", author_dn=dn
    )
    write_event(
        directory, action="modify", object_type="group", object_dn=f"cn=g,{BASE}", author_dn=ADMIN
    )
    found = audit.events_for(directory, dn)
    assert len(found) == 3
    stamps = [e.text("hrcAuditDateTime") or "" for e in found]
    assert stamps == sorted(stamps, reverse=True)


# --------------------------------------------------------------- paging


def empty_query(**overrides: object) -> AuditQuery:
    values: dict[str, object] = {
        "start": None,
        "end": None,
        "actor": "",
        "object": "",
        "actions": [],
        "type": "",
        "result": "",
        "q": "",
    }
    values.update(overrides)
    return AuditQuery(**values)  # type: ignore[arg-type]


def test_page_events_reads_newest_first_and_pages(directory: MemoryDirectory) -> None:
    if directory.get(AUDIT) is None:
        directory.add(AUDIT, {"objectClass": [b"organizationalUnit"], "ou": [b"audit"]})
    for minute in range(5):
        write_event(
            directory,
            action="modify",
            object_type="user",
            object_dn=f"uid=u{minute},{PEOPLE}",
            author_dn=ADMIN,
            now=NOW + timedelta(minutes=minute),
        )
    query = empty_query()
    first, more = page_events(directory, query, limit=2)
    assert [e.object for e in first] == [
        f"uid=u4,{PEOPLE}",
        f"uid=u3,{PEOPLE}",
    ]
    assert more is True

    second, more = page_events(directory, query, after=first[-1].sort_key, limit=2)
    assert [e.object for e in second] == [
        f"uid=u2,{PEOPLE}",
        f"uid=u1,{PEOPLE}",
    ]
    assert more is True

    last, more = page_events(directory, query, after=second[-1].sort_key, limit=2)
    assert [e.object for e in last] == [f"uid=u0,{PEOPLE}"]
    assert more is False


def test_page_events_applies_filters_while_reading(directory: MemoryDirectory) -> None:
    if directory.get(AUDIT) is None:
        directory.add(AUDIT, {"objectClass": [b"organizationalUnit"], "ou": [b"audit"]})
    for index, (action, login) in enumerate(
        [("login", "alice"), ("login", "bob"), ("modify", "alice"), ("login", "alice")]
    ):
        write_event(
            directory,
            action=action,
            object_type="user",
            object_dn=f"uid={login},{PEOPLE}",
            author_dn=ADMIN,
            attributes=[f"login: {login}"],
            now=NOW + timedelta(minutes=index),
        )
    query = empty_query(actions=["login"], q="alice")
    page, more = page_events(directory, query, limit=10)
    assert more is False
    assert [e.action for e in page] == ["login", "login"]
    assert all("login: alice" in e.attributes for e in page)
