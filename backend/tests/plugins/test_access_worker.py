"""The access worker pass: reminders, auto-closing reviews and orphaned requests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import heracles_plugins.access as access
import heracles_plugins.audit as audit
from heracles import demo
from heracles.auth.mail import MemoryMailer
from heracles.core.access_config import configure_access
from heracles.core.audit import AuditSink
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.objects.task_runner import TaskRunContext
from heracles.storage import Database
from heracles.storage.database import MEMORY
from heracles.tasks.auditing import AuditingDirectory
from heracles_plugins.access import grants as g
from heracles_plugins.access import reviews as rv
from heracles_plugins.access.requests import AccessRequestStore

BASE = demo.BASE
LYON_STAFF = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
LYON_MANAGERS = f"cn=lyon-managers,ou=roles,ou=lyon,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"
DLEFEVRE = f"uid=dlefevre,ou=people,ou=lyon,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _config():  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    configure_access(None)
    yield
    configure_access(None)


class Pass:
    """One directory, one application database and a context factory."""

    def __init__(self) -> None:
        self.directory = demo.build_demo_directory()
        self.directory.set_schema_object_classes(
            [*self.directory.schema_object_classes(), "hrcAuditEvent", "hrcGrantExpiries"]
        )
        self.registry = TypeRegistry()
        register_builtin_types(self.registry)
        classes = {c.lower() for c in self.directory.schema_object_classes()}
        self.registry.register_plugin(audit.plugin(), classes)
        self.registry.register_plugin(access.plugin(), classes)
        self.database = Database(MEMORY)
        self.mailer = MemoryMailer()
        self.requests = AccessRequestStore(self.database, clock=lambda: NOW.timestamp())
        self.reviews = rv.ReviewStore(self.database, clock=lambda: NOW.timestamp())

    def run(self, now: datetime = NOW, *, mailer: bool = True) -> access.AccessReport:
        directory = AuditingDirectory(
            self.directory, AuditSink(self.registry), source="task access"
        )
        ctx = TaskRunContext(
            directory=directory,
            now=now,
            settings=None,
            mailer=self.mailer if mailer else None,
            registry=self.registry,
            base_url="https://hrc.test/",
            database=self.database,
            directory_id="main",
        )
        return access._run(ctx)  # pyright: ignore[reportPrivateUsage]

    def audit_lines(self, action: str) -> list[str]:
        events = self.directory.search(f"ou=audit,{BASE}", f"(hrcAuditAction={action})")
        return [line for e in events for line in e.texts("hrcAuditAttributes")]

    def request(self, target: str = LYON_STAFF, member: str = ASMITH) -> str:
        return self.requests.add(
            directory_id="main",
            requester_dn=member,
            member_dn=member,
            target_dn=target,
            target_kind="member",
            target_label="lyon-staff",
            reason="needed",
            until=None,
        ).id

    def campaign(self, *, deadline: datetime, default: str = rv.REVOKE) -> rv.Campaign:
        campaign = rv.new_campaign(
            directory_id="main",
            name="Lyon Q4",
            creator=CDUPONT,
            deadline=deadline.timestamp(),
            rule="owner",
            default=default,
            selector={"holders": [LYON_STAFF], "base": ""},
            now=NOW.timestamp(),
        )
        item = rv.Item(
            campaign.id, "i1", LYON_STAFF, "lyon-staff", "member", DLEFEVRE, reviewer_dn=CDUPONT
        )
        self.reviews.create(campaign, [item])
        return campaign


@pytest.fixture
def env() -> Pass:
    return Pass()


def date_member(env: Pass, until: datetime, member: str = DLEFEVRE) -> None:
    g.set_end_date(env.directory, LYON_STAFF, "member", member, until)


# -- reminders -------------------------------------------------------------------------------


def test_a_reminder_goes_out_once_per_end_date(env: Pass) -> None:
    date_member(env, NOW + timedelta(days=3))
    report = env.run()
    assert report.reminders_sent == 1 and report.errors == []
    (mail,) = env.mailer.outbox
    assert mail.to == "dlefevre@heracles.test"
    assert "lyon-staff" in mail.subject and "2030-06-18" in mail.subject
    assert "https://hrc.test/me" in mail.body
    # the next pass (and the one after the window moved) does not repeat it
    assert env.run(NOW + timedelta(hours=1)).reminders_sent == 0
    assert len(env.mailer.outbox) == 1
    # moving the end date is a new grant end: reminded again
    date_member(env, NOW + timedelta(days=5))
    assert env.run(NOW + timedelta(hours=2)).reminders_sent == 1
    assert len(env.mailer.outbox) == 2


def test_no_reminder_outside_the_window_or_when_off(env: Pass) -> None:
    date_member(env, NOW + timedelta(days=30))
    assert env.run().reminders_sent == 0
    configure_access({"remind_days": 40})
    assert env.run().reminders_sent == 1
    configure_access({"remind_days": 0})
    date_member(env, NOW + timedelta(days=2))
    assert env.run().reminders_sent == 0 and len(env.mailer.outbox) == 1


def test_reminders_need_a_mailer_and_wait_for_one(env: Pass) -> None:
    date_member(env, NOW + timedelta(days=2))
    assert env.run(mailer=False).reminders_sent == 0
    assert env.run().reminders_sent == 1  # not marked as sent meanwhile


def test_a_failed_mail_is_retried_at_the_next_pass(
    env: Pass, monkeypatch: pytest.MonkeyPatch
) -> None:
    date_member(env, NOW + timedelta(days=2))

    def refuse(*_a: object, **_k: object) -> None:
        raise OSError("smtp down")

    monkeypatch.setattr(env.mailer, "send", refuse)
    report = env.run()
    assert report.reminders_sent == 0 and len(report.errors) == 1
    monkeypatch.undo()
    assert env.run().reminders_sent == 1


def test_a_custom_reminder_template_is_used(env: Pass) -> None:
    env.directory.add(
        f"cn=ending,ou=people,{BASE}",
        {
            "objectClass": [b"hrcMailTemplate"],
            "cn": [b"ending"],
            "hrcMailTemplateSubject": [b"Heads up: {target}"],
            "hrcMailTemplateBody": [b"until {until}"],
        },
    )
    configure_access({"mail": {"grant_expiring": "ending"}})
    date_member(env, NOW + timedelta(days=2))
    env.run()
    assert env.mailer.outbox[0].subject == "Heads up: lyon-staff"


def test_role_occupants_are_reminded_too(env: Pass) -> None:
    g.set_end_date(env.directory, LYON_MANAGERS, "roleOccupant", CDUPONT, NOW + timedelta(days=1))
    assert env.run().reminders_sent == 1
    assert env.mailer.outbox[0].to == "cdupont@heracles.test"


# -- auto-closing reviews --------------------------------------------------------------------


def test_an_overdue_campaign_is_closed_and_audited(env: Pass) -> None:
    campaign = env.campaign(deadline=NOW - timedelta(hours=1))
    report = env.run()
    assert report.reviews_closed == 1 and report.errors == []
    closed = env.reviews.get(campaign.id)
    assert closed is not None and closed.status == rv.CLOSED and closed.closed_by == ""
    entry = env.directory.get(LYON_STAFF)
    assert entry is not None and DLEFEVRE not in entry.texts("member")  # default: revoke
    lines = env.audit_lines("access_review")
    assert f"report sha256: {closed.report_hash}" in lines and "source: task access" in lines
    assert env.run(NOW + timedelta(minutes=1)).reviews_closed == 0  # once


def test_a_campaign_before_its_deadline_is_left_open(env: Pass) -> None:
    campaign = env.campaign(deadline=NOW + timedelta(days=1))
    assert env.run().reviews_closed == 0
    found = env.reviews.get(campaign.id)
    assert found is not None and found.status == rv.OPEN


def test_auto_close_can_be_turned_off(env: Pass) -> None:
    campaign = env.campaign(deadline=NOW - timedelta(hours=1))
    configure_access({"auto_close": False})
    assert env.run().reviews_closed == 0
    found = env.reviews.get(campaign.id)
    assert found is not None and found.status == rv.OPEN


def test_a_close_that_stopped_is_resumed_and_failures_are_reported(
    env: Pass, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign = env.campaign(deadline=NOW - timedelta(hours=1))
    real = env.directory.modify

    def refuse(dn: str, changes: object) -> None:
        raise g.DirectoryError("busy")

    monkeypatch.setattr(env.directory, "modify", refuse)
    report = env.run()
    assert report.reviews_closed == 0 and len(report.errors) == 1
    found = env.reviews.get(campaign.id)
    assert found is not None and found.status == rv.CLOSING
    monkeypatch.setattr(env.directory, "modify", real)
    assert env.run(NOW + timedelta(minutes=1)).reviews_closed == 1
    found = env.reviews.get(campaign.id)
    assert found is not None and found.status == rv.CLOSED


def test_other_directories_campaigns_are_not_touched(env: Pass) -> None:
    campaign = rv.new_campaign(
        directory_id="other",
        name="x",
        creator=CDUPONT,
        deadline=(NOW - timedelta(days=1)).timestamp(),
        rule="owner",
        default=rv.KEEP,
        selector={},
        now=NOW.timestamp(),
    )
    env.reviews.create(
        campaign, [rv.Item(campaign.id, "i", LYON_STAFF, "x", "member", DLEFEVRE, reviewer_dn="")]
    )
    assert env.run().reviews_closed == 0


# -- orphaned requests -----------------------------------------------------------------------


def test_a_request_for_a_deleted_group_is_cancelled_and_audited(env: Pass) -> None:
    kept = env.request()
    env.directory.delete(LYON_STAFF)
    other = env.request(target=LYON_MANAGERS, member=DLEFEVRE)
    report = env.run()
    assert report.requests_orphaned == 1
    gone = env.requests.get(kept)
    assert gone is not None and gone.status == "cancelled"
    assert gone.comment == "the group or role no longer exists" and gone.decided_by == ""
    still = env.requests.get(other)
    assert still is not None and still.status == "pending"
    lines = env.audit_lines("access_request")
    assert f"request: {kept}" in lines and "status: cancelled" in lines
    assert "source: task access" in lines
    assert [m.to for m in env.mailer.outbox] == ["asmith@heracles.test"]
    assert env.run(NOW + timedelta(minutes=1)).requests_orphaned == 0


def test_without_an_application_database_only_expiry_runs(env: Pass) -> None:
    date_member(env, NOW - timedelta(minutes=1))
    ctx = TaskRunContext(
        directory=env.directory, now=NOW, settings=None, mailer=env.mailer, registry=env.registry
    )
    report = access._run(ctx)  # pyright: ignore[reportPrivateUsage]
    assert report.grants_expired == 1 and report.reminders_sent == 0


def test_the_pass_is_clean_on_an_untouched_directory(env: Pass) -> None:
    report = env.run()
    assert report.errors == []
    assert (report.reminders_sent, report.reviews_closed, report.requests_orphaned) == (0, 0, 0)
