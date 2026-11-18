"""API v2/v1: locks, moves, snapshots listing and counters honour the ACLs."""

from __future__ import annotations

import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.acl import ResolvedAcl, serialise_assignment, serialise_role_value
from heracles.acl.model import AclAssignment, AclScope, RoleTemplateValue
from heracles.acl.parser import parse_role_value
from heracles.api import domain
from heracles.demo import BASE
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.schema.names import ATTR, OC
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

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v2{path}", headers=self.headers)


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
    session.cache["acl.epoch"] = 4
    cached = domain._cached_resolution  # pyright: ignore[reportPrivateUsage]
    assert cached(cast("Any", session), 4) is fresh
    assert cached(cast("Any", session), 5) is None  # roles or assignments changed since
    fresh.resolved_at -= domain.ACL_CACHE_SECONDS + 1
    assert cached(cast("Any", session), 4) is None


def test_snapshot_restore_cannot_write_what_the_caller_may_not(app: FastAPI) -> None:
    """The restore right does not let a caller put back an attribute they cannot write."""
    directory = cast("MemoryDirectory", app.state.heracles.directories["main"])
    role = f"cn=snapshots-only,ou=aclroles,{BASE}"
    parsed = parse_role_value("0:user/user;r#snapshot;rw")
    assert isinstance(parsed, RoleTemplateValue)
    directory.add(
        role,
        {
            "objectClass": [OC.ACL_ROLE.encode()],
            "cn": [b"snapshots-only"],
            ATTR.ACL_TEMPLATE: [serialise_role_value(parsed).encode()],
        },
    )
    member = f"uid=bmartin,ou=people,{PARIS}"
    grant = AclAssignment(index=0, scope=AclScope.SUBTREE, role_dn=role, members=(member,))
    directory.modify(
        PARIS,
        [
            Modification("add", "objectClass", [OC.ACL_ASSIGNMENT.encode()]),
            Modification("add", ATTR.ACL_ENTRY, [serialise_assignment(grant).encode()]),
        ],
    )
    admin = login(app, "admin")
    snap = admin.post(f"/objects/user/{q(ASMITH)}/snapshots", {}).json()["id"]
    old = directory.get(ASMITH)
    assert old is not None
    directory.modify(ASMITH, [Modification("replace", "userPassword", [b"{SSHA}changed"])])

    r = login(app, "bmartin").post(f"/snapshots/{q(snap)}/restore")

    assert r.status_code == 403, r.text
    now = directory.get(ASMITH)
    assert now is not None and now.text("userPassword") == "{SSHA}changed"


@pytest.mark.parametrize("action", ["lock", "delete", "password"])
def test_account_changes_end_its_open_sessions(app: FastAPI, action: str) -> None:
    """Locking, deleting or resetting the password of an account signs its sessions out at once."""
    victim = login(app, "bmartin")
    assert victim.get("/auth/me").status_code == 200
    target = f"uid=bmartin,ou=people,{PARIS}"
    admin = login(app, "admin")
    if action == "lock":
        r = admin.post(f"/users/{q(target)}/lock")
    elif action == "delete":
        r = admin.delete(f"/objects/user/{q(target)}")
    else:
        body = {"tabs": {"main": {"values": {"userPassword": "N3w-passw0rd-long-enough"}}}}
        r = admin.patch(f"/objects/user/{q(target)}", body)
    assert r.status_code in (200, 204), r.text
    assert victim.get("/types").status_code == 401


@pytest.mark.parametrize("recreated", [False, True])
def test_session_does_not_outlive_its_entry(app: FastAPI, recreated: bool) -> None:
    """An entry removed behind the API's back (or replaced under the same DN) ends its sessions."""
    victim = login(app, "bmartin")
    assert victim.get("/auth/me").status_code == 200
    directory = cast("MemoryDirectory", app.state.heracles.directories["main"])
    dn = f"uid=bmartin,ou=people,{PARIS}"
    old = directory.get(dn)
    assert old is not None
    directory.delete(dn)
    if recreated:
        directory.add(dn, {k: v for k, v in old.attrs.items() if k != "entryUUID"})
    app.state.heracles.clock = lambda: time.time() + 3600  # past the periodic re-check
    assert victim.get("/types").status_code == 401
