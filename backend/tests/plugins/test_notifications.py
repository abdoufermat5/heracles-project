"""Notifications plugin: snapshot comparison, mails, templates, schedule, CRUD."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import heracles_plugins.notifications as nt
from heracles.auth.mail import MemoryMailer
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
TASKS = f"ou=tasks,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
TASK_DN = f"cn=watch,{TASKS}"
TEMPLATE_DN = f"cn=changed,ou=mailTemplate,{BASE}"
HR = f"uid=hr,{PEOPLE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(
        [*d.schema_object_classes(), "hrcTasksNotifications", "hrcMailTemplate"]
    )
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for dn, ou in (
        (PEOPLE, "people"),
        (GROUPS, "groups"),
        (TASKS, "tasks"),
        (f"ou=mailTemplate,{BASE}", "mailTemplate"),
    ):
        d.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.add(
        TEMPLATE_DN,
        {
            "objectClass": [b"hrcMailTemplate"],
            "cn": [b"changed"],
            "hrcMailTemplateSubject": [b"{uid} changed: {attributes}"],
            "hrcMailTemplateBody": [b"{cn} <{mail}>\n{changes}\n{unknown}"],
        },
    )
    d.add(
        HR,
        {
            "objectClass": [b"inetOrgPerson"],
            "uid": [b"hr"],
            "cn": [b"HR"],
            "sn": [b"HR"],
            "mail": [b"hr@example.com"],
        },
    )
    return d


def add_user(d: MemoryDirectory, uid: str, **extra: str) -> str:
    dn = f"uid={uid},{PEOPLE}"
    attrs = {
        "objectClass": [b"inetOrgPerson"],
        "uid": [uid.encode()],
        "cn": [uid.encode()],
        "sn": [b"Doe"],
        "mail": [f"{uid}@example.com".encode()],
    }
    attrs.update({k: [v.encode()] for k, v in extra.items()})
    d.add(dn, attrs)
    return dn


def add_task(
    d: MemoryDirectory, monitored: list[str], attributes: str = "mail|telephoneNumber"
) -> None:
    d.add(
        TASK_DN,
        {
            "objectClass": [b"hrcTasks", b"hrcTasksNotifications"],
            "cn": [b"watch"],
            "hrcTasksStatus": [b"Activated"],
            "hrcTasksRepeatable": [b"TRUE"],
            "hrcTasksRepeatableSchedule": [b"hourly"],
            "hrcTasksNotificationsAttributes": [a.encode() for a in attributes.split("|")],
            "hrcTasksNotificationsMailTemplate": [TEMPLATE_DN.encode()],
            "hrcTasksNotificationsEmailSender": [b"noreply@example.com"],
            "hrcTasksNotificationsMonitoredMembers": [m.encode() for m in monitored],
            "hrcTasksNotificationsRecipientsMembers": [HR.encode()],
        },
    )


def run(d: MemoryDirectory, mailer: MemoryMailer, at: datetime = NOW) -> nt.NotificationsReport:
    return nt.run_notifications(d, mailer, at, nt.NotificationsSettings())


def test_first_run_only_records_then_changes_are_mailed(directory: MemoryDirectory) -> None:
    a = add_user(directory, "alice", telephoneNumber="111")
    add_task(directory, [a])
    mailer = MemoryMailer()
    first = run(directory, mailer)
    assert first.snapshots_written == 1 and first.mails_sent == 0
    assert nt.load_snapshots(directory, TASK_DN)[a.lower()] == {
        "mail": ["alice@example.com"],
        "telephoneNumber": ["111"],
    }
    # nothing changed: nothing sent
    assert run(directory, mailer, NOW + timedelta(hours=1)).mails_sent == 0
    directory.modify(
        a,
        [
            Modification("replace", "telephoneNumber", [b"222"]),
            Modification("replace", "mail", [b"a2@example.com"]),
        ],
    )
    report = run(directory, mailer, NOW + timedelta(hours=2))
    assert report.mails_sent == 1 and report.snapshots_written == 1
    mail = mailer.outbox[0]
    assert mail.to == "hr@example.com" and mail.sender == "noreply@example.com"
    assert mail.subject == "alice changed: mail, telephoneNumber"
    assert "mail: alice@example.com -> a2@example.com" in mail.body
    assert "telephoneNumber: 111 -> 222" in mail.body
    assert "alice <a2@example.com>" in mail.body and "{unknown}" in mail.body
    assert report.notifications[0].recipients == ("hr@example.com",)
    # the new values are the reference: no new mail
    assert run(directory, mailer, NOW + timedelta(hours=3)).mails_sent == 0


def test_added_and_removed_values(directory: MemoryDirectory) -> None:
    a = add_user(directory, "alice")
    add_task(directory, [a])
    mailer = MemoryMailer()
    run(directory, mailer)
    directory.modify(a, [Modification("add", "telephoneNumber", [b"333"])])
    run(directory, mailer, NOW + timedelta(hours=1))
    directory.modify(a, [Modification("delete", "telephoneNumber")])
    run(directory, mailer, NOW + timedelta(hours=2))
    assert "telephoneNumber: (empty) -> 333" in mailer.outbox[0].body
    assert "telephoneNumber: 333 -> (empty)" in mailer.outbox[1].body


def test_group_members_new_members_and_stale_snapshots(directory: MemoryDirectory) -> None:
    a = add_user(directory, "alice")
    b = add_user(directory, "bob")
    group = f"cn=team,{GROUPS}"
    directory.add(
        group, {"objectClass": [b"groupOfNames"], "cn": [b"team"], "member": [a.encode()]}
    )
    add_task(directory, [group])
    mailer = MemoryMailer()
    run(directory, mailer)
    directory.modify(group, [Modification("replace", "member", [b.encode()])])
    report = run(directory, mailer, NOW + timedelta(hours=1))
    # bob is new (recorded only), alice left the group (snapshot dropped)
    assert report.mails_sent == 0
    assert list(nt.load_snapshots(directory, TASK_DN)) == [b.lower()]


def test_unmonitored_and_forbidden_attributes_are_ignored(directory: MemoryDirectory) -> None:
    a = add_user(directory, "alice", userPassword="{SSHA}one", description="x")
    add_task(directory, [a], attributes="userPassword|description|mail")
    mailer = MemoryMailer()
    run(directory, mailer)
    directory.modify(
        a,
        [
            Modification("replace", "userPassword", [b"{SSHA}two"]),
            Modification("replace", "description", [b"y"]),
        ],
    )
    assert run(directory, mailer, NOW + timedelta(hours=1)).mails_sent == 0
    snap = nt.load_snapshots(directory, TASK_DN)[a.lower()]
    assert list(snap) == ["mail"]


def test_missing_template_attributes_and_errors(directory: MemoryDirectory) -> None:
    a = add_user(directory, "alice")
    add_task(directory, [a], attributes="userPassword")
    report = run(directory, MemoryMailer())
    assert report.tasks_run == 0 and "no monitored attribute" in report.errors[0]
    directory.delete(TASK_DN)
    add_task(directory, [a])
    directory.delete(TEMPLATE_DN)
    report = run(directory, MemoryMailer())
    assert report.tasks_run == 0 and "mail template not found" in report.errors[0]


def test_mail_failure_is_reported(directory: MemoryDirectory) -> None:
    class Broken:
        def send(self, to: str, subject: str, body: str, *, sender: str | None = None) -> None:
            raise OSError("smtp down")

    a = add_user(directory, "alice")
    add_task(directory, [a])
    run(directory, MemoryMailer())
    directory.modify(a, [Modification("replace", "mail", [b"new@example.com"])])
    report = nt.run_notifications(
        directory, Broken(), NOW + timedelta(hours=1), nt.NotificationsSettings()
    )
    assert report.mails_sent == 0 and "failed" in report.errors[0]


def test_task_type_validation_and_snapshot_cleanup_on_delete(directory: MemoryDirectory) -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    assert registry.register_plugin(
        nt.plugin(), {c.lower() for c in directory.schema_object_classes()}
    ).enabled
    info = registry.get("notifications_task")
    assert info.acl_object(info.main_tab) == "tasks/notificationsTask"
    assert info.type.filter == "(&(objectClass=hrcTasks)(objectClass=hrcTasksNotifications))"
    a = add_user(directory, "alice")
    service = ObjectService(directory, registry)
    values = {
        "cn": "watch",
        "hrcTasksNotificationsAttributes": ["mail"],
        "hrcTasksNotificationsMailTemplate": TEMPLATE_DN,
        "hrcTasksNotificationsEmailSender": "noreply@example.com",
        "hrcTasksNotificationsMonitoredMembers": [a],
        "hrcTasksNotificationsRecipientsMembers": [HR],
        "hrcTasksRepeatable": True,
        "hrcTasksRepeatableSchedule": "daily",
    }
    dn = service.create("notifications_task", BASE, {"main": {"values": values}})
    assert dn == TASK_DN
    run(directory, MemoryMailer())
    assert nt.load_snapshots(directory, dn)
    service.delete("notifications_task", dn)
    assert directory.get(dn) is None
    with pytest.raises(ObjectValidationError):
        service.create(
            "notifications_task",
            BASE,
            {"main": {"values": {**values, "hrcTasksNotificationsAttributes": ["userPassword"]}}},
        )
