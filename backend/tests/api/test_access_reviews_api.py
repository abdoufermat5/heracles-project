"""Access reviews: a campaign closes with revocations applied and an exportable report."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings, PluginsSettings
from heracles.api.state import AppState
from heracles.auth.mail import MemoryMailer
from heracles.core.access_config import configure_access
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app
from tests.api.test_audit_api import Api

BASE = demo.BASE
LYON_STAFF = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
ADMINS = f"cn=admins,ou=groups,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"
DLEFEVRE = f"uid=dlefevre,ou=people,ou=lyon,{BASE}"
ADMIN = f"uid=admin,ou=people,{BASE}"


@pytest.fixture(autouse=True)
def _config() -> Iterator[None]:
    configure_access(None)
    yield
    configure_access(None)


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


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


def as_user(client: TestClient, uid: str) -> Api:
    client.cookies.clear()
    a = Api(client)
    assert a.login(uid).status_code == 200
    return a


def deadline(days: int = 7) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


def create(client: TestClient, **body: object) -> dict[str, Any]:
    a = as_user(client, "admin")
    r = a.post(
        "/access/reviews",
        {"name": "Lyon Q4", "holders": [LYON_STAFF], "deadline": deadline(), **body},
    )
    assert r.status_code == 201, r.text
    return r.json()["campaign"]


def test_campaign_flows_to_reviewers_and_closes_with_revocations(
    client: TestClient, directory: MemoryDirectory, mailer: MemoryMailer
) -> None:
    campaign = create(client)
    assert campaign["counts"]["items"] == 2
    assert any("Access review: Lyon Q4" in m.subject for m in mailer.outbox)

    owner = as_user(client, "cdupont")
    assert owner.get("/access/queue").json()["reviews"] == 1
    listing = owner.get("/access/reviews").json()
    assert [c["id"] for c in listing["items"]] == [campaign["id"]] and not listing["can_manage"]
    detail = owner.get(f"/access/reviews/{campaign['id']}").json()
    # the owner reviews dlefevre, never their own membership (that goes to the creator)
    assert [i["member"] for i in detail["items"]] == [DLEFEVRE]
    item = detail["items"][0]
    r = owner.post(
        f"/access/reviews/{campaign['id']}/items/{item['id']}",
        {"decision": "revoke", "comment": "left the team"},
    )
    assert r.status_code == 200 and r.json()["item"]["decision"] == "revoke"

    admin = as_user(client, "admin")
    full = admin.get(f"/access/reviews/{campaign['id']}").json()
    own = next(i for i in full["items"] if i["member"] == CDUPONT)
    assert own["reviewer"].lower() == ADMIN.lower()
    closed = admin.post(f"/access/reviews/{campaign['id']}/close").json()
    assert closed["failed"] == [] and closed["campaign"]["status"] == "closed"
    digest = closed["campaign"]["report_hash"]
    assert len(digest) == 64

    entry = directory.get(LYON_STAFF)
    assert entry is not None and entry.texts("member") == [CDUPONT]  # undecided: kept
    outcomes = {
        i["member"]: i["outcome"]
        for i in admin.get(f"/access/reviews/{campaign['id']}").json()["items"]
    }
    assert outcomes == {CDUPONT: "kept", DLEFEVRE: "revoked"}

    # the report is exported behind step-up and hashes to the value in the audit log
    report = admin.get(f"/access/reviews/{campaign['id']}/report")
    assert report.status_code == 200 and report.headers["x-report-sha256"] == digest
    assert report.json()["sha256"] == digest and report.json()["matches"] is True
    assert report.headers["x-report-matches"] == "true"
    csv_report = admin.get(f"/access/reviews/{campaign['id']}/report", format="csv")
    assert csv_report.text.splitlines()[0].startswith("holder,kind,member")
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=access_review)"))
    lines = [line for e in events for line in e.texts("hrcAuditAttributes")]
    assert f"report sha256: {digest}" in lines


def test_report_needs_a_recent_sign_in(client: TestClient) -> None:
    campaign = create(client)
    admin = as_user(client, "admin")
    state: AppState = client.app.state.heracles  # type: ignore[attr-defined]
    state.clock = lambda: time.time() + 3600
    r = admin.get(f"/access/reviews/{campaign['id']}/report")
    assert r.status_code == 403 and r.json()["error"]["code"] == "reauth_required"


def test_rules(client: TestClient) -> None:
    a = as_user(client, "asmith")
    body = {"name": "x", "holders": [LYON_STAFF], "deadline": deadline()}
    assert a.post("/access/reviews", body).status_code == 403
    admin = as_user(client, "admin")
    past = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    assert admin.post("/access/reviews", {**body, "deadline": past}).status_code == 422
    assert admin.post("/access/reviews", {**body, "reviewer": "boss"}).status_code == 422
    assert admin.post("/access/reviews", {**body, "holders": [f"uid=x,{BASE}"]}).status_code == 422

    campaign = create(client)
    other = as_user(client, "dlefevre")  # neither reviewer nor manager
    assert other.get(f"/access/reviews/{campaign['id']}").status_code == 404
    owner = as_user(client, "cdupont")
    item = owner.get(f"/access/reviews/{campaign['id']}").json()["items"][0]
    assert (
        owner.post(
            f"/access/reviews/{campaign['id']}/items/{item['id']}", {"decision": "drop"}
        ).status_code
        == 422
    )
    assert owner.post(f"/access/reviews/{campaign['id']}/close").status_code == 403


def test_default_revoke_and_last_member_rule(
    client: TestClient, directory: MemoryDirectory
) -> None:
    campaign = create(client, holders=[ADMINS], default="revoke")
    admin = as_user(client, "admin")
    closed = admin.post(f"/access/reviews/{campaign['id']}/close").json()
    assert closed["campaign"]["status"] == "closed"
    (item,) = admin.get(f"/access/reviews/{campaign['id']}").json()["items"]
    assert item["outcome"] == "kept: last member"
    entry = directory.get(ADMINS)
    assert entry is not None and entry.texts("member") == [ADMIN]
    assert admin.post(f"/access/reviews/{campaign['id']}/close").status_code == 409


def test_manager_rule_and_department_selection(
    client: TestClient, directory: MemoryDirectory
) -> None:
    from heracles.ldap.client import Modification

    directory.modify(DLEFEVRE, [Modification("replace", "manager", [CDUPONT.encode()])])
    campaign = create(client, holders=[], base=f"ou=lyon,{BASE}", reviewer="manager")
    admin = as_user(client, "admin")
    items = admin.get(f"/access/reviews/{campaign['id']}").json()["items"]
    reviewers = {(i["holder"]["label"], i["member"]): i["reviewer"] for i in items}
    assert reviewers[("lyon-staff", DLEFEVRE)].lower() == CDUPONT.lower()
    # no manager: the creator reviews
    assert reviewers[("lyon-staff", CDUPONT)].lower() == ADMIN.lower()
    assert ("lyon-managers", CDUPONT) in reviewers  # roles below the department too


def test_a_close_that_failed_resumes(
    client: TestClient, directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heracles_plugins.access import reviews as rv

    campaign = create(client, default="revoke")  # both members revoked by default
    real = rv.revoke_one
    calls = {"n": 0}

    def flaky(*args: object, **kwargs: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("directory busy")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(rv, "revoke_one", flaky)
    admin = as_user(client, "admin")
    first = admin.post(f"/access/reviews/{campaign['id']}/close").json()
    assert first["campaign"]["status"] == "closing" and len(first["failed"]) == 1
    second = admin.post(f"/access/reviews/{campaign['id']}/close").json()
    assert second["campaign"]["status"] == "closed" and second["failed"] == []
    outcomes = sorted(
        i["outcome"] for i in admin.get(f"/access/reviews/{campaign['id']}").json()["items"]
    )
    # one revoked; the other was then the last member of the group and stays
    assert outcomes == ["kept: last member", "revoked"]


def test_a_read_token_of_a_configured_administrator_does_not_manage_reviews(
    directory: MemoryDirectory,
) -> None:
    """The campaign manager view (every item, the report) is the cap-bound right on ACL
    assignments, not the bare administrator list."""
    settings = ApiSettings(
        admin_dns=[ADMIN], directory_labels={"main": "Demo"}, plugins=PluginsSettings(enabled=["*"])
    )
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        a = Api(client)
        a.login("admin")
        r = a.post("/auth/tokens", {"name": "ro", "scope": "read", "expires_in_days": 7})
        assert r.status_code == 201, r.text
        headers = {"Authorization": f"Bearer {r.json()['secret']}"}
        assert a.get("/access/reviews").json()["can_manage"] is True
        client.cookies.clear()
        listed = client.get("/api/v2/access/reviews", headers=headers)
        assert listed.status_code == 200 and listed.json()["can_manage"] is False
