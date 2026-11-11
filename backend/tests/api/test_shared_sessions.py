"""Two applications on one database file stand in for two worker processes."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.app import create_app
from heracles.api.settings import ApiSettings, DatabaseSettings
from heracles.api.state import AppState
from heracles.auth.ratelimit_db import SqliteRateLimiter
from heracles.auth.sessions_db import SqliteSessionStore
from tests.api.conftest import Clock
from tests.auth.fakes import FakeDirectory

PASSWORD = "s3cretpass"


def _workers(path: Path) -> tuple[TestClient, TestClient, Clock]:
    clock = Clock()
    directory = FakeDirectory()
    user_dn = directory.add_user("jdoe", PASSWORD, mail="jdoe@example.com", cn="John Doe")

    def build() -> TestClient:
        settings = ApiSettings(
            directory_labels={"main": "Main"},
            admin_dns=[user_dn],
            database=DatabaseSettings(path=path),
        )
        app = create_app(settings, {"main": directory}, clock=clock)
        return TestClient(app, base_url="https://testserver", raise_server_exceptions=False)

    return build(), build(), clock


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": str(client.get("/api/v2/auth/csrf").json()["token"])}


def _share_cookies(source: TestClient, target: TestClient) -> None:
    for name, value in source.cookies.items():
        target.cookies.set(name, value)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": "jdoe", "password": PASSWORD},
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "methods": []}


def test_the_default_stores_live_in_the_database(tmp_path: Path) -> None:
    a, _, _ = _workers(tmp_path / "h.db")
    state = cast(AppState, cast(FastAPI, a.app).state.heracles)
    assert isinstance(state.sessions, SqliteSessionStore)
    assert isinstance(state.limiter, SqliteRateLimiter)


def test_login_on_one_worker_and_logout_on_it_are_seen_by_the_other(tmp_path: Path) -> None:
    a, b, _ = _workers(tmp_path / "h.db")
    _login(a)
    _share_cookies(a, b)

    me = b.get("/api/v2/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["uid"] == "jdoe"

    logout = a.post("/api/v2/auth/logout", headers=_csrf(a))
    assert logout.status_code == 204
    assert b.get("/api/v2/auth/me").status_code == 401


def test_a_confirmed_password_is_remembered_by_every_worker(tmp_path: Path) -> None:
    a, b, clock = _workers(tmp_path / "h.db")
    _login(a)
    _share_cookies(a, b)

    clock.advance(6 * 60)  # past the window in which a fresh login allows sensitive changes
    refused = b.post("/api/v2/auth/totp/begin", headers=_csrf(b))
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "reauth_required"

    confirmed = a.post("/api/v2/auth/reauth", json={"password": PASSWORD}, headers=_csrf(a))
    assert confirmed.status_code == 200, confirmed.text

    allowed = b.post("/api/v2/auth/totp/begin", headers=_csrf(b))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["secret"]
