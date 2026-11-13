"""API v2/v1: locks, moves, snapshots listing and counters honour the ACLs."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.acl import ResolvedAcl
from heracles.api import domain
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
DLEFEVRE = f"uid=dlefevre,ou=people,ou=lyon,{BASE}"
PARIS = f"ou=paris,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str) -> Api:
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": username, "password": "heracles"},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        return self

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def patch(self, path: str, body: Any) -> Any:
        return self.client.patch(f"/api/v2{path}", json=body, headers=self.headers)


@pytest.fixture
def app() -> Iterator[FastAPI]:
    app = build_demo_app()
    with TestClient(app):
        yield app


def login(app: FastAPI, username: str) -> Api:
    # one client (cookie jar) per user
    return Api(TestClient(app)).login(username)


def test_lock_needs_an_edit_right(app: FastAPI) -> None:
    path = f"/objects/user/{q(ASMITH)}/lock"
    assert login(app, "bmartin").post(path).status_code == 403
    assert login(app, "admin").post(path).status_code == 200


def test_snapshot_list_needs_read_right(app: FastAPI) -> None:
    path = f"/objects/user/{q(ASMITH)}/snapshots"
    assert login(app, "bmartin").get(path).status_code == 403
    assert login(app, "admin").get(path).status_code == 200


def test_dashboard_does_not_count_unreadable_locked_accounts(app: FastAPI) -> None:
    admin = login(app, "admin")
    assert admin.post(f"/users/{q(ASMITH)}/lock").status_code == 200
    assert admin.get("/dashboard").json()["locked_users"] == 1
    assert login(app, "bmartin").get("/dashboard").json()["locked_users"] == 0


def test_move_needs_move_right(app: FastAPI) -> None:
    body = {"base": PARIS}
    assert login(app, "helpdesk").post(f"/objects/user/{q(DLEFEVRE)}/move", body).status_code == 403
    r = login(app, "admin").post(f"/objects/user/{q(DLEFEVRE)}/move", body)
    assert r.status_code == 200, r.text
    new_dn = r.json()["dn"]
    assert new_dn == f"uid=dlefevre,ou=people,{PARIS}"
    directory = cast("MemoryDirectory", app.state.heracles.directories["main"])
    assert directory.get(new_dn) is not None and directory.get(DLEFEVRE) is None


def test_manager_cannot_move_out_of_their_department(app: FastAPI) -> None:
    """Write access to the department attribute is not the right to move to another one."""
    manager = login(app, "cdupont")
    r = manager.patch(
        f"/objects/user/{q(DLEFEVRE)}", {"tabs": {"main": {"values": {"base": PARIS}}}}
    )
    assert r.status_code == 403, r.text
    r = manager.post(f"/objects/user/{q(DLEFEVRE)}/move", {"base": PARIS})
    assert r.status_code == 403, r.text
    directory = cast("MemoryDirectory", app.state.heracles.directories["main"])
    assert directory.get(DLEFEVRE) is not None


def test_template_use_needs_rights_on_its_department(app: FastAPI) -> None:
    admin = login(app, "admin")
    r = admin.post(
        "/types/user/templates",
        {"name": "staff", "base": BASE, "tabs": {"main": {"values": {"description": "x"}}}},
    )
    assert r.status_code == 201, r.text
    template = r.json()["dn"]
    manager = login(app, "cdupont")  # may create users in Lyon, not at the top
    r = manager.post(
        "/objects/user",
        {
            "base": f"ou=lyon,{BASE}",
            "template": template,
            "tabs": {"main": {"values": {"sn": "T", "givenName": "T", "uid": "tt"}}},
        },
    )
    assert r.status_code == 403, r.text
    assert manager.get(f"/types/user/templates/{q(template)}/fields").status_code == 403


def test_cached_acl_resolution_expires() -> None:
    session = SimpleNamespace(cache={})
    fresh = ResolvedAcl("uid=x,dc=example,dc=com")
    session.cache["acl.resolved"] = fresh
    assert domain._cached_resolution(cast("Any", session)) is fresh  # pyright: ignore[reportPrivateUsage]
    fresh.resolved_at -= domain.ACL_CACHE_SECONDS + 1
    assert domain._cached_resolution(cast("Any", session)) is None  # pyright: ignore[reportPrivateUsage]
