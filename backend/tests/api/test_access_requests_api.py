"""Access requests: portal to approver to directory."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from heracles import demo
from heracles.api.settings import ApiSettings, PluginsSettings
from heracles.auth.mail import MemoryMailer
from heracles.core.access_config import configure_access
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app
from heracles.storage import Database
from heracles_plugins.access import grants as g
from tests.api.test_audit_api import Api

BASE = demo.BASE
LYON_STAFF = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
ADMINS = f"cn=admins,ou=groups,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"
BMARTIN = f"uid=bmartin,ou=people,ou=paris,{BASE}"
DLEFEVRE = f"uid=dlefevre,ou=people,ou=lyon,{BASE}"


@pytest.fixture(autouse=True)
def _config() -> Iterator[None]:
    configure_access({"max_days": 90})
    yield
    configure_access(None)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = demo.build_demo_directory()
    entry = d.get(LYON_STAFF)
    assert entry is not None and entry.texts("owner") == [CDUPONT]  # the demo owner
    return d


@pytest.fixture
def mailer() -> MemoryMailer:
    return MemoryMailer()


@pytest.fixture
def client(directory: MemoryDirectory, mailer: MemoryMailer) -> Iterator[TestClient]:
    settings = ApiSettings(
        admin_dns=[], directory_labels={"main": "Demo"}, plugins=PluginsSettings(enabled=["*"])
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": directory})
    app.state.heracles.mailer = mailer
    with TestClient(app) as c:
        yield c


def soon(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


def as_user(client: TestClient, uid: str) -> Api:
    client.cookies.clear()
    a = Api(client)
    assert a.login(uid).status_code == 200
    return a


def submit(client: TestClient, **body: object) -> dict[str, object]:
    a = as_user(client, "asmith")
    r = a.post(
        "/access/requests",
        {"target": LYON_STAFF, "reason": "On call in Lyon", "until": soon(), **body},
    )
    assert r.status_code == 201, r.text
    return r.json()["request"]


def test_requestable_lists_owned_groups_not_held(client: TestClient) -> None:
    a = as_user(client, "asmith")
    items = a.get("/access/requestable").json()["items"]
    assert [i["dn"] for i in items] == [LYON_STAFF]
    assert items[0]["kind"] == "member"
    # a member does not see what they already hold
    b = as_user(client, "cdupont")
    assert b.get("/access/requestable").json()["items"] == []


def test_request_flows_to_the_owner_and_into_the_directory(
    client: TestClient, directory: MemoryDirectory, mailer: MemoryMailer
) -> None:
    created = submit(client)
    assert created["status"] == "pending"
    assert any("Access request: lyon-staff" in m.subject for m in mailer.outbox)

    owner = as_user(client, "cdupont")
    queue = owner.get("/access/requests", view="to_approve").json()["items"]
    assert [r["id"] for r in queue] == [created["id"]]
    assert owner.get("/access/queue").json() == {"approvals": 1, "reviews": 0}
    r = owner.post(f"/access/requests/{created['id']}/approve", {"comment": "ok"})
    assert r.status_code == 200, r.text
    assert r.json()["request"]["status"] == "approved"

    entry = directory.get(LYON_STAFF)
    assert entry is not None and ASMITH in entry.texts("member")
    (grant,) = g.grants_of(entry)
    assert grant.member == ASMITH and grant.until.date().isoformat() == soon()
    assert any("was approved" in m.subject for m in mailer.outbox)
    # the change is in the audit log with the approver as author
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=access_request)"))
    assert {e.text("hrcAuditAuthorDN") for e in events} >= {ASMITH, CDUPONT}
    mine = as_user(client, "asmith").get("/access/requests").json()["items"]
    assert mine[0]["status"] == "approved"


def test_only_approvers_decide_and_never_their_own(client: TestClient) -> None:
    created = submit(client)
    other = as_user(client, "bmartin")
    assert other.get("/access/requests", view="to_approve").json()["items"] == []
    assert other.post(f"/access/requests/{created['id']}/approve", {}).status_code == 403
    me = as_user(client, "asmith")
    assert me.post(f"/access/requests/{created['id']}/approve", {}).status_code == 403


def test_rejection_needs_a_comment_and_is_final(
    client: TestClient, directory: MemoryDirectory
) -> None:
    created = submit(client)
    owner = as_user(client, "cdupont")
    assert owner.post(f"/access/requests/{created['id']}/reject", {}).status_code == 422
    r = owner.post(f"/access/requests/{created['id']}/reject", {"comment": "not needed"})
    assert r.json()["request"]["status"] == "rejected"
    assert owner.post(f"/access/requests/{created['id']}/approve", {}).status_code == 409
    entry = directory.get(LYON_STAFF)
    assert entry is not None and ASMITH not in entry.texts("member")


def test_request_rules(client: TestClient) -> None:
    a = as_user(client, "asmith")
    base = {"target": LYON_STAFF, "reason": "x", "until": soon()}
    assert a.post("/access/requests", {**base, "target": ADMINS}).status_code == 422  # no owner
    assert a.post("/access/requests", {**base, "reason": " "}).status_code == 422
    assert a.post("/access/requests", {**base, "until": None}).status_code == 422  # max_days
    assert a.post("/access/requests", {**base, "until": soon(200)}).status_code == 422
    assert a.post("/access/requests", base).status_code == 201
    assert a.post("/access/requests", base).status_code == 422  # one pending at a time


def test_cancel_by_the_requester(client: TestClient) -> None:
    created = submit(client)
    assert (
        as_user(client, "cdupont").post(f"/access/requests/{created['id']}/cancel").status_code
        == 404
    )
    r = as_user(client, "asmith").post(f"/access/requests/{created['id']}/cancel")
    assert r.json()["request"]["status"] == "cancelled"


def test_configured_approver_group(client: TestClient) -> None:
    created = submit(client)
    assert (
        as_user(client, "dlefevre")
        .post(f"/access/requests/{created['id']}/approve", {})
        .status_code
        == 403
    )
    # members of a configured approver group decide any request (dlefevre is in lyon-staff)
    configure_access({"max_days": 90, "approvers": [LYON_STAFF]})
    r = as_user(client, "dlefevre").post(f"/access/requests/{created['id']}/approve", {})
    assert r.json()["request"]["status"] == "approved"


def test_failed_dating_undoes_the_membership(
    client: TestClient, directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = submit(client)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("dating refused")

    monkeypatch.setattr(g, "set_end_date", boom)
    r = as_user(client, "cdupont").post(f"/access/requests/{created['id']}/approve", {})
    assert r.status_code == 200
    done = r.json()["request"]
    assert done["status"] == "failed" and "dating refused" in done["error"]
    entry = directory.get(LYON_STAFF)
    assert entry is not None and ASMITH not in entry.texts("member")


def test_a_dated_membership_can_be_extended(client: TestClient, directory: MemoryDirectory) -> None:
    created = submit(client)
    as_user(client, "cdupont").post(f"/access/requests/{created['id']}/approve", {})
    a = as_user(client, "asmith")
    (item,) = a.get("/access/requestable").json()["items"]
    assert item["dn"] == LYON_STAFF and item["renews"] is not None
    r = a.post(
        "/access/requests", {"target": LYON_STAFF, "reason": "still on call", "until": soon(60)}
    )
    assert r.status_code == 201, r.text
    as_user(client, "cdupont").post(f"/access/requests/{r.json()['request']['id']}/approve", {})
    entry = directory.get(LYON_STAFF)
    assert entry is not None
    (grant,) = g.grants_of(entry)
    assert grant.until.date().isoformat() == soon(60)
    assert entry.texts("member").count(ASMITH) == 1


# -- requests for others ---------------------------------------------------------------------


def make_manager(directory: MemoryDirectory, person: str, manager: str) -> None:
    directory.modify(person, [g.Modification("add", "manager", [manager.encode()])])


def ask_for(client: TestClient, uid: str, member: str, **body: object) -> Response:
    return as_user(client, uid).post(
        "/access/requests",
        {"target": LYON_STAFF, "reason": "Joins the team", "until": soon(), "member": member}
        | body,
    )


def test_a_manager_asks_for_their_report(
    client: TestClient, directory: MemoryDirectory, mailer: MemoryMailer
) -> None:
    make_manager(directory, BMARTIN, ASMITH)
    r = ask_for(client, "asmith", BMARTIN)
    assert r.status_code == 201, r.text
    created = r.json()["request"]
    assert created["member"] == BMARTIN and created["requester"] == ASMITH
    # approvers are mailed, and so is the person the request is for
    recipients = {m.to: m.subject for m in mailer.outbox}
    assert "Access request: lyon-staff" in recipients["cdupont@heracles.test"]
    assert "Access request for you" in recipients["bmartin@heracles.test"]
    assert "asmith@heracles.test" not in recipients
    # both parties see it, and the one who asked may cancel it
    for uid in ("asmith", "bmartin"):
        mine = as_user(client, uid).get("/access/requests").json()["items"]
        assert [i["id"] for i in mine] == [created["id"]]
    # neither the person nor the one who asked may approve it; the owner does
    assert (
        as_user(client, "asmith").post(f"/access/requests/{created['id']}/approve", {}).status_code
        == 403
    )
    assert (
        as_user(client, "bmartin").post(f"/access/requests/{created['id']}/approve", {}).status_code
        == 403
    )
    mailer.outbox.clear()
    done = as_user(client, "cdupont").post(f"/access/requests/{created['id']}/approve", {})
    assert done.json()["request"]["status"] == "approved"
    entry = directory.get(LYON_STAFF)
    assert entry is not None and BMARTIN in entry.texts("member")
    assert ASMITH not in entry.texts("member")
    assert {m.to for m in mailer.outbox} == {"asmith@heracles.test", "bmartin@heracles.test"}
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=access_request)"))
    assert any(f"member: {BMARTIN}" in e.texts("hrcAuditAttributes") for e in events)


def test_the_requester_of_someone_else_may_cancel(
    client: TestClient, directory: MemoryDirectory
) -> None:
    make_manager(directory, BMARTIN, ASMITH)
    created = ask_for(client, "asmith", BMARTIN).json()["request"]
    r = as_user(client, "asmith").post(f"/access/requests/{created['id']}/cancel")
    assert r.json()["request"]["status"] == "cancelled"


def test_whoever_manages_access_asks_for_anyone(
    client: TestClient, directory: MemoryDirectory
) -> None:
    r = ask_for(client, "admin", BMARTIN)
    assert r.status_code == 201, r.text
    assert r.json()["request"]["member"] == BMARTIN
    # an ACL role granting assignment writes is enough too: not tested here, the check is
    # ``can_manage`` as for review campaigns
    assert ask_for(client, "admin", f"uid=nobody,ou=people,{BASE}").status_code == 422


def test_nobody_else_asks_for_others(client: TestClient, directory: MemoryDirectory) -> None:
    make_manager(directory, BMARTIN, CDUPONT)  # cdupont manages bmartin, not asmith
    r = ask_for(client, "asmith", BMARTIN)
    assert r.status_code == 403
    assert ask_for(client, "asmith", f"uid=nobody,ou=people,{BASE}").status_code == 403
    # nothing was filed
    assert as_user(client, "bmartin").get("/access/requests").json()["items"] == []


def test_asking_for_oneself_by_dn_is_the_plain_request(client: TestClient) -> None:
    r = ask_for(client, "asmith", ASMITH.upper())
    assert r.status_code == 201
    assert r.json()["request"]["member"] == ASMITH


def test_rules_apply_to_the_person_asked_for(
    client: TestClient, directory: MemoryDirectory
) -> None:
    make_manager(directory, DLEFEVRE, ASMITH)
    # dlefevre already is a (permanent) member
    assert ask_for(client, "asmith", DLEFEVRE).status_code == 422
    make_manager(directory, BMARTIN, ASMITH)
    assert ask_for(client, "asmith", BMARTIN).status_code == 201
    assert ask_for(client, "asmith", BMARTIN).status_code == 422  # one pending per person
    # while asmith may still ask for themselves
    assert ask_for(client, "asmith", ASMITH).status_code == 201


def test_the_person_asked_for_is_never_an_approver_of_it(
    client: TestClient, directory: MemoryDirectory
) -> None:
    approvers = f"cn=approvers,ou=groups,{BASE}"
    directory.add(
        approvers,
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"approvers"],
            "member": [BMARTIN.encode(), DLEFEVRE.encode()],
        },
    )
    configure_access({"max_days": 90, "approvers": [approvers]})
    make_manager(directory, BMARTIN, ASMITH)
    created = ask_for(client, "asmith", BMARTIN).json()["request"]
    # bmartin approves any request, but not the one for themselves; nor does the requester
    assert (
        as_user(client, "bmartin").post(f"/access/requests/{created['id']}/approve", {}).status_code
        == 403
    )
    assert (
        as_user(client, "asmith").post(f"/access/requests/{created['id']}/approve", {}).status_code
        == 403
    )
    done = as_user(client, "dlefevre").post(f"/access/requests/{created['id']}/approve", {})
    assert done.json()["request"]["status"] == "approved"


def test_requests_live_in_the_schedulers_database(client: TestClient) -> None:
    from heracles.tasks.wiring import attach_scheduler
    from heracles_plugins.access.requests import AccessRequestStore

    # the in-process worker of the demo: its database is the one the API stores use
    attach_scheduler(client.app, start=False)  # type: ignore[arg-type]
    submit(client)
    database = cast(Database, client.app.state.task_store.database)  # type: ignore[attr-defined]
    assert [r.requester_dn for r in AccessRequestStore(database).list("main")] == [ASMITH]
