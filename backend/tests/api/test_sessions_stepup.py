"""Active sessions (self-service and administrator revoke) and step-up of sensitive changes."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.app import create_app
from heracles.api.settings import ApiSettings, DatabaseSettings
from heracles.api.state import AppState
from heracles.auth.second_factor import WebAuthnCredential
from heracles.demo import BASE
from heracles.server import build_demo_app
from heracles_plugins.audit.events import events_for
from tests.api.conftest import Clock
from tests.auth.fakes import FakeDirectory

ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"


class Api:
    def __init__(self, app: FastAPI, agent: str = "pytest") -> None:
        self.client = TestClient(app, base_url="http://testserver")
        self.client.headers["user-agent"] = agent
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str, password: str = "heracles") -> Api:
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": username, "password": password},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        return self

    def get(self, path: str) -> Any:
        return self.client.get(f"/api/v2{path}")

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v2{path}", headers=self.headers)


@pytest.fixture
def app() -> FastAPI:
    return build_demo_app()


@pytest.fixture
def state(app: FastAPI) -> Iterator[AppState]:
    with TestClient(app):
        yield cast("AppState", app.state.heracles)


def _actions(state: AppState) -> list[str | None]:
    return [e.text("hrcAuditAction") for e in events_for(state.directories["main"], ASMITH)]


# -- self-service sessions ------------------------------------------------------------------------
def test_sessions_are_listed_and_revoked(app: FastAPI, state: AppState) -> None:
    laptop = Api(app, "Firefox on Linux").login("asmith")
    phone = Api(app, "Safari on iOS").login("asmith")
    listed = laptop.get("/auth/sessions").json()
    assert sorted(s["user_agent"] for s in listed) == ["Firefox on Linux", "Safari on iOS"]
    assert [s["user_agent"] for s in listed if s["current"]] == ["Firefox on Linux"]
    assert all(s["ip"] and "id" in s for s in listed)

    other = next(s for s in listed if not s["current"])
    assert laptop.delete(f"/auth/sessions/{other['id']}").status_code == 204
    assert phone.get("/auth/me").status_code == 401  # the revoked session is gone
    assert laptop.delete(f"/auth/sessions/{other['id']}").status_code == 404

    assert _actions(state).count("logout") == 1


def test_a_session_cannot_revoke_itself_or_see_others_sessions(app: FastAPI) -> None:
    mine = Api(app).login("asmith")
    theirs = Api(app).login("bmartin")
    [current] = mine.get("/auth/sessions").json()
    assert mine.delete(f"/auth/sessions/{current['id']}").status_code == 422
    assert theirs.delete(f"/auth/sessions/{current['id']}").status_code == 404
    assert mine.get("/auth/me").status_code == 200


def test_revoke_others_keeps_the_current_session(app: FastAPI) -> None:
    a, b, c = (Api(app).login("asmith") for _ in range(3))
    assert a.post("/auth/sessions/revoke-others").json() == {"revoked": 2}
    assert b.get("/auth/me").status_code == 401 and c.get("/auth/me").status_code == 401
    assert a.get("/auth/me").status_code == 200


# -- administrator: sign a user out everywhere ---------------------------------------------------
def test_admin_revokes_all_sessions_of_a_user(app: FastAPI, state: AppState) -> None:
    victim = Api(app).login("asmith")
    helpdesk = Api(app).login("helpdesk")
    r = helpdesk.delete(f"/users/{quote(ASMITH, safe='')}/sessions")
    assert r.status_code == 200 and r.json() == {"revoked": 1}
    assert victim.get("/auth/me").status_code == 401
    assert _actions(state).count("logout") == 1
    # a normal user may not
    assert (
        Api(app).login("bmartin").delete(f"/users/{quote(ASMITH, safe='')}/sessions").status_code
        == 403
    )


def test_admin_actions_need_a_recent_confirmation(app: FastAPI, state: AppState) -> None:
    state.second_factor.store.add_webauthn_credential(
        ASMITH, WebAuthnCredential(b"k", b"pk", 0, "key")
    )
    helpdesk = Api(app).login("helpdesk")
    state.clock = lambda: time.time() + 3600  # the login is now an hour old
    for r in (
        helpdesk.delete(f"/users/{quote(ASMITH, safe='')}/sessions"),
        helpdesk.delete(f"/users/{quote(ASMITH, safe='')}/second-factors"),
    ):
        assert r.status_code == 403 and r.json()["error"]["code"] == "reauth_required"
    assert helpdesk.post("/auth/reauth", {"password": "heracles"}).status_code == 200
    r = helpdesk.delete(f"/users/{quote(ASMITH, safe='')}/second-factors")
    assert r.status_code == 204


def test_own_password_change_needs_a_recent_confirmation(app: FastAPI, state: AppState) -> None:
    me = Api(app).login("asmith")
    state.clock = lambda: time.time() + 3600
    dn = quote(ASMITH, safe="")
    body = {"tabs": {"main": {"active": True, "values": {"userPassword": "Another-pass-1"}}}}
    r = me.client.patch(f"/api/v2/objects/user/{dn}", json=body, headers=me.headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "reauth_required"
    assert me.post("/auth/reauth", {"password": "heracles"}).status_code == 200
    r = me.client.patch(f"/api/v2/objects/user/{dn}", json=body, headers=me.headers)
    assert r.status_code != 403, r.text


# -- sessions on the application database --------------------------------------------------------
def test_sessions_on_the_database_are_shared_and_revocable(tmp_path: Path) -> None:
    clock = Clock()
    directory = FakeDirectory()
    user_dn = directory.add_user("jdoe", "s3cretpass", cn="John Doe")

    def worker() -> TestClient:
        settings = ApiSettings(
            directory_labels={"main": "Main"},
            admin_dns=[user_dn],
            database=DatabaseSettings(path=tmp_path / "h.db"),
        )
        app = create_app(settings, {"main": directory}, clock=clock)
        return TestClient(app, base_url="https://testserver")

    a, b = worker(), worker()
    for client in (a, b):
        client.headers["user-agent"] = "UA-" + str(id(client))
        token = str(client.get("/api/v2/auth/csrf").json()["token"])
        r = client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "jdoe", "password": "s3cretpass"},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200
        client.headers["X-CSRF-Token"] = str(client.get("/api/v2/auth/csrf").json()["token"])
    listed = a.get("/api/v2/auth/sessions").json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    assert all(s["user_agent"].startswith("UA-") for s in listed)
    assert a.post("/api/v2/auth/sessions/revoke-others").json() == {"revoked": 1}
    assert b.get("/api/v2/auth/me").status_code == 401
    assert len(a.get("/api/v2/auth/sessions").json()) == 1
