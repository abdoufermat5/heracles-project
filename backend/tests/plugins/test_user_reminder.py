"""User reminder plugin: members, day selection, templates, tokens, schedules, CRUD."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import heracles_plugins.user_reminder as ur
from heracles.auth.mail import MemoryMailer
from heracles.core.generalized_time import format_generalized_time
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.user_reminder.prolong import ProlongError, prolong_account
from heracles_plugins.user_reminder.runner import hash_token

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
ROLES = f"ou=roles,{BASE}"
TASKS = f"ou=tasks,{BASE}"
TOKENS = f"ou=reminder,ou=tokens,ou=fusiondirectory,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
TODAY = NOW.date()
EPOCH = date(1970, 1, 1)
TEMPLATE_DN = f"cn=expiry,ou=mailTemplate,{BASE}"
TASK_DN = f"cn=expiry,{TASKS}"
URL = "https://heracles.example"


def days(d: date) -> str:
    return str((d - EPOCH).days)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes([*d.schema_object_classes(), "fdTasksReminder", "fdMailTemplate"])
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for dn, ou in ((PEOPLE, "people"), (GROUPS, "groups"), (ROLES, "roles")):
        d.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.add(
        f"ou=mailTemplate,{BASE}",
        {"objectClass": [b"organizationalUnit"], "ou": [b"mailTemplate"]},
    )
    d.add(
        TEMPLATE_DN,
        {
            "objectClass": [b"fdMailTemplate"],
            "cn": [b"expiry"],
            "fdMailTemplateSubject": [b"Account {uid} expires in {days_left} days"],
            "fdMailTemplateBody": [
                b"Hi {givenName} {sn} ({cn}, {mail}): expires {expiration_date}. "
                b"{prolongation_url} {unknown}"
            ],
        },
    )
    return d


def add_user(d: MemoryDirectory, uid: str, expire: date | None, mail: str | None = "auto") -> str:
    dn = f"uid={uid},{PEOPLE}"
    attrs = {
        "objectClass": [b"inetOrgPerson", b"posixAccount", b"shadowAccount"],
        "uid": [uid.encode()],
        "cn": [f"{uid} Doe".encode()],
        "givenName": [uid.encode()],
        "sn": [b"Doe"],
    }
    if mail:
        attrs["mail"] = [(f"{uid}@example.com" if mail == "auto" else mail).encode()]
    if expire is not None:
        attrs["shadowExpire"] = [days(expire).encode()]
    d.add(dn, attrs)
    return dn


def add_task(d: MemoryDirectory, members: list[str], **extra: str) -> str:
    if d.get(TASKS) is None:
        d.add(TASKS, {"objectClass": [b"organizationalUnit"], "ou": [b"tasks"]})
    attrs: dict[str, list[bytes]] = {
        "objectClass": [b"fdTasks", b"fdTasksReminder"],
        "cn": [b"expiry"],
        "fdTasksStatus": [b"Activated"],
        "fdTasksRepeatable": [b"TRUE"],
        "fdTasksRepeatableSchedule": [b"daily"],
        "fdTasksReminderFirstCall": [b"30"],
        "fdTasksReminderSecondCall": [b"7"],
        "fdTasksReminderPosix": [b"TRUE"],
        "fdTasksReminderAccountProlongation": [b"FALSE"],
        "fdTasksReminderMailTemplate": [TEMPLATE_DN.encode()],
        "fdTasksReminderEmailSender": [b"noreply@example.com"],
        "fdTasksReminderMembers": [m.encode() for m in members],
    }
    for key, value in extra.items():
        attrs[key] = [v.encode() for v in value.split("|")] if value else []
    d.add(TASK_DN, {k: v for k, v in attrs.items() if v})
    return TASK_DN


def run(d: MemoryDirectory, mailer: MemoryMailer, now: datetime = NOW) -> ur.RunReport:
    return ur.run_reminders(d, mailer, now, URL, ur.UserReminderSettings())


def task_entry(d: MemoryDirectory) -> Entry:
    entry = d.get(TASK_DN)
    assert entry is not None
    return entry


# ----------------------------------------------------------------- members


def test_expand_users_groups_roles(directory: MemoryDirectory) -> None:
    a = add_user(directory, "a", TODAY)
    b = add_user(directory, "b", TODAY)
    c = add_user(directory, "c", TODAY)
    directory.add(
        f"cn=g,{GROUPS}",
        {"objectClass": [b"groupOfNames"], "cn": [b"g"], "member": [a.encode(), b.encode()]},
    )
    directory.add(
        f"cn=outer,{GROUPS}",
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"outer"],
            "member": [f"cn=g,{GROUPS}".encode()],
        },
    )
    directory.add(
        f"cn=r,{ROLES}",
        {"objectClass": [b"organizationalRole"], "cn": [b"r"], "roleOccupant": [c.encode()]},
    )
    found = ur.expand_members(
        directory, [f"cn=outer,{GROUPS}", f"cn=r,{ROLES}", a, f"uid=ghost,{PEOPLE}"]
    )
    assert sorted(e.dn for e in found) == sorted([a, b, c])


# ----------------------------------------------------------- day selection


def test_first_and_second_call_only(directory: MemoryDirectory) -> None:
    users = {
        "first": TODAY + timedelta(days=30),
        "second": TODAY + timedelta(days=7),
        "other": TODAY + timedelta(days=8),
        "past": TODAY - timedelta(days=7),
    }
    dns = [add_user(directory, uid, when) for uid, when in users.items()]
    dns.append(add_user(directory, "noexpire", None))
    add_task(directory, dns)
    mailer = MemoryMailer()
    report = run(directory, mailer)
    assert report.tasks_run == 1
    assert sorted((r.user_dn, r.days_left) for r in report.reminders) == sorted(
        [(f"uid=first,{PEOPLE}", 30), (f"uid=second,{PEOPLE}", 7)]
    )
    assert sorted(m.to for m in mailer.outbox) == ["first@example.com", "second@example.com"]


def test_same_call_days_send_once(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "u", TODAY + timedelta(days=7))
    add_task(directory, [dn], fdTasksReminderFirstCall="7", fdTasksReminderSecondCall="7")
    mailer = MemoryMailer()
    run(directory, mailer)
    assert len(mailer.outbox) == 1


# --------------------------------------------------------------- templates


def test_template_rendering(directory: MemoryDirectory) -> None:
    when = TODAY + timedelta(days=7)
    dn = add_user(directory, "jdoe", when)
    add_task(directory, [dn])
    mailer = MemoryMailer()
    run(directory, mailer)
    (mail,) = mailer.outbox
    assert mail.subject == "Account jdoe expires in 7 days"
    assert mail.sender == "noreply@example.com"
    assert mail.body == (
        f"Hi jdoe Doe (jdoe Doe, jdoe@example.com): expires {when.isoformat()}.  {{unknown}}"
    )


def test_render_template_is_safe() -> None:
    assert ur.render_template("{uid} {x}", {"uid": "a"}) == "a {x}"
    assert ur.render_template("{uid", {"uid": "a"}) == "{uid"
    assert ur.render_template("{uid.__class__}", {"uid": "a"}) != ""


# -------------------------------------------------------------- recipients


def test_copy_recipients_and_missing_mail(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "u", TODAY + timedelta(days=30))
    boss = add_user(directory, "boss", None)
    hr = add_user(directory, "hr", None, mail="hr@example.com")
    directory.add(
        f"cn=staff,{GROUPS}",
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"staff"],
            "member": [boss.encode(), hr.encode()],
        },
    )
    add_task(directory, [dn], fdTasksReminderRecipientsMembers=f"cn=staff,{GROUPS}")
    mailer = MemoryMailer()
    report = run(directory, mailer)
    assert sorted(m.to for m in mailer.outbox) == [
        "boss@example.com",
        "hr@example.com",
        "u@example.com",
    ]
    assert report.mails_sent == 3
    assert len(set(m.body for m in mailer.outbox)) == 1


def test_user_without_mail_still_notifies_recipients(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "u", TODAY + timedelta(days=30), mail=None)
    hr = add_user(directory, "hr", None)
    add_task(directory, [dn], fdTasksReminderRecipientsMembers=hr)
    mailer = MemoryMailer()
    run(directory, mailer)
    assert [m.to for m in mailer.outbox] == ["hr@example.com"]


# ------------------------------------------------------------------ tokens


def test_token_created_hashed_and_link_in_mail(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "jdoe", TODAY + timedelta(days=7))
    add_task(directory, [dn], fdTasksReminderAccountProlongation="TRUE")
    mailer = MemoryMailer()
    report = run(directory, mailer)
    assert report.tokens_created == 1
    (mail,) = mailer.outbox
    prefix = f"{URL}/reminder/prolong?login=jdoe&token="
    link = next(w for w in mail.body.split() if w.startswith(prefix))
    token = link.removeprefix(prefix)
    (stored,) = list(directory.search(TOKENS, "(objectClass=fdTokenEntry)"))
    assert token not in stored.dn
    assert stored.text("fdToken") == hash_token(token)
    assert stored.text("fdTokenType") == "reminder"
    assert stored.text("fdTokenUserDN") == dn
    assert int(stored.text("fdTokenTimestamp") or 0) == int(NOW.timestamp()) + 7 * 86400
    assert token.encode() not in b"".join(v for vs in stored.attrs.values() for v in vs)


def prolongable(directory: MemoryDirectory, expire: date) -> tuple[str, str]:
    dn = add_user(directory, "jdoe", expire)
    token = ur.create_prolongation_token(directory, dn, now=NOW, valid_days=7)
    return dn, token


def test_prolongation_extends_from_expiry_and_consumes_token(directory: MemoryDirectory) -> None:
    expire = TODAY + timedelta(days=7)
    dn, token = prolongable(directory, expire)
    new = prolong_account(directory, "jdoe", token, days=30, now=NOW)
    assert new == expire + timedelta(days=30)
    entry = directory.get(dn)
    assert entry is not None and entry.text("shadowExpire") == days(new)
    assert list(directory.search(TOKENS, "(objectClass=fdTokenEntry)")) == []
    with pytest.raises(ProlongError):
        prolong_account(directory, "jdoe", token, days=30, now=NOW)  # reuse


def test_prolongation_of_already_expired_account_counts_from_today(
    directory: MemoryDirectory,
) -> None:
    _, token = prolongable(directory, TODAY - timedelta(days=100))
    assert prolong_account(directory, "jdoe", token, days=30, now=NOW) == TODAY + timedelta(days=30)


def test_expired_token_wrong_user_and_wrong_token(directory: MemoryDirectory) -> None:
    dn, token = prolongable(directory, TODAY + timedelta(days=7))
    add_user(directory, "other", TODAY + timedelta(days=7))
    with pytest.raises(ProlongError):
        prolong_account(directory, "other", token, days=30, now=NOW)
    with pytest.raises(ProlongError):
        prolong_account(directory, "jdoe", token + "x", days=30, now=NOW)
    with pytest.raises(ProlongError):
        prolong_account(directory, "nobody", token, days=30, now=NOW)
    with pytest.raises(ProlongError):
        prolong_account(directory, "jdoe", token, days=30, now=NOW + timedelta(days=8))
    entry = directory.get(dn)
    assert entry is not None and entry.text("shadowExpire") == days(TODAY + timedelta(days=7))


def test_new_token_replaces_previous(directory: MemoryDirectory) -> None:
    dn, first = prolongable(directory, TODAY + timedelta(days=7))
    second = ur.create_prolongation_token(directory, dn, now=NOW, valid_days=7)
    assert len(list(directory.search(TOKENS, "(objectClass=fdTokenEntry)"))) == 1
    with pytest.raises(ProlongError):
        prolong_account(directory, "jdoe", first, days=30, now=NOW)
    prolong_account(directory, "jdoe", second, days=30, now=NOW)


# --------------------------------------------------------------- schedules


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        ("hourly", datetime(2030, 6, 15, 9, 0, tzinfo=UTC)),
        ("daily", datetime(2030, 6, 16, 8, 0, tzinfo=UTC)),
        ("weekly", datetime(2030, 6, 22, 8, 0, tzinfo=UTC)),
        ("monthly", datetime(2030, 7, 15, 8, 0, tzinfo=UTC)),
        ("yearly", datetime(2031, 6, 15, 8, 0, tzinfo=UTC)),
    ],
)
def test_next_execution(schedule: str, expected: datetime) -> None:
    assert ur.next_execution(NOW, schedule) == expected


def test_next_execution_clamps_month_end_and_unknown() -> None:
    assert ur.next_execution(datetime(2030, 1, 31, tzinfo=UTC), "monthly") == datetime(
        2030, 2, 28, tzinfo=UTC
    )
    assert ur.next_execution(datetime(2032, 2, 29, tzinfo=UTC), "yearly") == datetime(
        2033, 2, 28, tzinfo=UTC
    )
    assert ur.next_execution(NOW, "fortnightly") is None


def test_repeatable_task_is_rescheduled_and_not_due_twice(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "u", TODAY + timedelta(days=7))
    add_task(directory, [dn], fdTasksRepeatableSchedule="weekly")
    mailer = MemoryMailer()
    run(directory, mailer)
    task = task_entry(directory)
    assert task.text("fdTasksLastExec") == format_generalized_time(NOW)
    assert task.text("fdTasksNextExec") == format_generalized_time(NOW + timedelta(weeks=1))
    assert task.text("fdTasksStatus") == "Activated"
    report = run(directory, mailer, NOW + timedelta(hours=1))
    assert report.tasks_run == 0 and len(mailer.outbox) == 1
    assert run(directory, mailer, NOW + timedelta(weeks=1)).tasks_run == 1


def test_non_repeatable_task_is_deactivated(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "u", TODAY + timedelta(days=7))
    add_task(directory, [dn], fdTasksRepeatable="FALSE")
    mailer = MemoryMailer()
    run(directory, mailer)
    task = task_entry(directory)
    assert task.text("fdTasksStatus") == "Deactivated"
    assert task.text("fdTasksNextExec") is None
    assert run(directory, mailer, NOW + timedelta(days=1)).tasks_run == 0


def test_deactivated_task_and_missing_template_are_skipped(directory: MemoryDirectory) -> None:
    dn = add_user(directory, "u", TODAY + timedelta(days=7))
    add_task(directory, [dn], fdTasksStatus="Deactivated")
    mailer = MemoryMailer()
    assert run(directory, mailer).tasks_run == 0
    directory.delete(TASK_DN)
    add_task(directory, [dn], fdTasksReminderMailTemplate=f"cn=gone,{BASE}")
    report = run(directory, mailer)
    assert report.tasks_run == 0 and report.errors and not mailer.outbox
    assert task_entry(directory).text("fdTasksLastExec") is None


def test_runner_without_tasks_container(directory: MemoryDirectory) -> None:
    assert run(directory, MemoryMailer()).tasks_examined == 0


# --------------------------------------------------------------------- CRUD


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        ur.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    assert registry.settings["user_reminder"].prolongation_days == 30
    return ObjectService(directory, registry)


def test_plugin_disabled_without_schema() -> None:
    registry = TypeRegistry()
    status = registry.register_plugin(ur.plugin(), set())
    assert not status.enabled and status.missing_object_classes == ["fdTasks", "fdTasksReminder"]


def test_reminder_task_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    schedule = "2030-07-01T10:00:00Z"
    add_user(directory, "a", None)
    dn = service.create(
        "reminder_task",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "expiry",
                    "fdTasksReminderFirstCall": 30,
                    "fdTasksReminderSecondCall": 7,
                    "fdTasksReminderPosix": False,
                    "fdTasksReminderMailTemplate": TEMPLATE_DN,
                    "fdTasksReminderEmailSender": "noreply@example.com",
                    "fdTasksReminderMembers": [f"uid=a,{PEOPLE}"],
                    "fdTasksScheduleDate": schedule,
                    "fdTasksRepeatable": True,
                    "fdTasksRepeatableSchedule": "weekly",
                }
            }
        },
    )
    assert dn == TASK_DN
    entry = task_entry(directory)
    assert entry.has_object_class("fdTasks") and entry.has_object_class("fdTasksReminder")
    assert entry.text("fdTasksReminderPosix") == "TRUE"
    assert entry.text("fdTasksStatus") == "Activated"
    assert entry.text("fdTasksNextExec") == "20300701100000Z"
    assert entry.text("fdTasksCreationDate")
    assert entry.text("fdTasksRepeatable") == "TRUE"
    state = service.load("reminder_task", dn)
    assert state.tabs["main"].values["fdTasksReminderFirstCall"] == 30
    service.update("reminder_task", dn, {"main": {"values": {"fdTasksReminderFirstCall": 14}}})
    assert task_entry(directory).text("fdTasksReminderFirstCall") == "14"
    assert [e.dn for e in directory.search(BASE, "(&(objectClass=fdTasks)(cn=expiry))")] == [dn]
    service.delete("reminder_task", dn)
    assert directory.get(dn) is None


def test_reminder_task_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError):
        service.create("reminder_task", BASE, {"main": {"values": {"cn": "x"}}})
    with pytest.raises(ObjectValidationError):
        service.create(
            "reminder_task",
            BASE,
            {
                "main": {
                    "values": {
                        "cn": "x",
                        "fdTasksReminderFirstCall": 5,
                        "fdTasksReminderMailTemplate": TEMPLATE_DN,
                        "fdTasksReminderEmailSender": "a@example.com",
                        "fdTasksReminderMembers": [f"uid=a,{PEOPLE}"],
                        "fdTasksRepeatable": True,
                    }
                }
            },
        )


def test_mail_template_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "mail_template",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "second",
                    "fdMailTemplateSubject": "Hi {uid}",
                    "fdMailTemplateBody": "Bye {uid}",
                }
            }
        },
    )
    assert dn == f"cn=second,ou=mailTemplate,{BASE}"
    entry = directory.get(dn)
    assert entry is not None and entry.text("fdMailTemplateBody") == "Bye {uid}"
