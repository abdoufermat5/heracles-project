"""Access requests: portal to approver to directory."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings, PluginsSettings
from heracles.auth.mail import MemoryMailer
from heracles.core.access_config import configure_access
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app
from heracles_plugins.access import grants as g
from tests.api.test_audit_api import Api

BASE = demo.BASE
LYON_STAFF = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
ADMINS = f"cn=admins,ou=groups,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"
BMARTIN = f"uid=bmartin,ou=people,ou=paris,{BASE}"


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
    assert owner.get("/access/queue").json() == {"approvals": 1}
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
