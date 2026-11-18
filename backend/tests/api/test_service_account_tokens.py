"""API tokens owned by service accounts (``dsa`` objects): scripts without a person behind."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.state import AppState
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

HELPDESK_ROLE = f"cn=helpdesk,ou=aclroles,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    def __init__(self, app: FastAPI) -> None:
        self.client = TestClient(app, base_url="http://testserver")
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str) -> Api:
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": username, "password": "heracles"},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        return self

    def call(self, method: str, path: str, body: Any = None) -> Any:
        return self.client.request(method, f"/api/v2{path}", json=body, headers=self.headers)


@pytest.fixture
def app() -> FastAPI:
    return build_demo_app()


@pytest.fixture
def directory(app: FastAPI) -> MemoryDirectory:
    return cast("MemoryDirectory", cast("AppState", app.state.heracles).directories["main"])


def create_account(admin: Api, cn: str = "backup-agent") -> str:
    r = admin.call(
        "POST",
        "/objects/dsa",
        {
            "base": BASE,
            "tabs": {
                "main": {"active": True, "values": {"cn": cn, "userPassword": "S3rvice-pass"}}
            },
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["dn"])


def grant_helpdesk(admin: Api, account: str) -> None:
    """Give the account the helpdesk role on the whole tree (reads users, no groups)."""
    items = admin.call("GET", f"/admin/acl/assignments/{q(BASE)}").json()["assignments"]
    items.append(
        {"index": len(items), "scope": "subtree", "role": HELPDESK_ROLE, "members": [account]}
    )
    r = admin.call("PUT", f"/admin/acl/assignments/{q(BASE)}", {"assignments": items})
    assert r.status_code == 200, r.text


def mint(admin: Api, account: str, **body: Any) -> Any:
    payload: dict[str, Any] = {"name": "nightly backup", "scope": "write", "expires_in_days": 30}
    payload.update(body)
    return admin.call("POST", f"/service-accounts/{q(account)}/tokens", payload)


def test_a_service_account_token_acts_with_the_account_rights(app: FastAPI) -> None:
    admin = Api(app).login("admin")
    account = create_account(admin)
    grant_helpdesk(admin, account)
    r = mint(admin, account)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["owner_dn"] == account
    assert created["created_by"] == f"uid=admin,ou=people,{BASE}"
    auth = {"Authorization": f"Bearer {created['secret']}"}
    bot = TestClient(app, base_url="http://testserver")

    users = bot.get("/api/v2/objects/user", params={"base": BASE, "scope": "sub"}, headers=auth)
    assert users.status_code == 200, users.text
    assert ASMITH in {i["dn"] for i in users.json()["items"]}
    # helpdesk reads no groups: the account's ACL applies, not the creator's
    groups = bot.get("/api/v2/objects/group", params={"base": BASE, "scope": "sub"}, headers=auth)
    assert groups.status_code == 200 and groups.json()["items"] == []
    scim = bot.get("/scim/v2/Users", headers=auth)
    assert scim.status_code == 200, scim.text

    # routes about "me" answer for the account or refuse it, never fail
    for path in (
        "/api/v2/auth/me",
        "/api/v2/auth/me/groups",
        "/api/v2/me/applications",
        "/api/v2/dashboard",
        "/api/v2/access/me",
        "/api/v2/access/requestable",
    ):
        answer = bot.get(path, headers=auth)
        assert answer.status_code < 500, (path, answer.text)
        assert answer.status_code in (200, 403, 404), (path, answer.status_code, answer.text)
    filed = bot.post(
        "/api/v2/access/requests",
        json={"target": f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}", "reason": "x", "until": None},
        headers=auth,
    )
    assert filed.status_code < 500, filed.text

    listed = admin.call("GET", f"/service-accounts/{q(account)}/tokens").json()
    assert [t["id"] for t in listed] == [created["id"]]
    assert (
        admin.call("DELETE", f"/service-accounts/{q(account)}/tokens/{created['id']}").status_code
        == 204
    )
    assert bot.get("/api/v2/auth/me", headers=auth).status_code == 401


def test_only_whoever_may_set_the_password_mints_and_never_with_a_token(app: FastAPI) -> None:
    admin = Api(app).login("admin")
    account = create_account(admin)
    # a self-service user may not
    portal = Api(app).login("asmith")
    assert mint(portal, account).status_code == 403
    assert portal.call("GET", f"/service-accounts/{q(account)}/tokens").status_code == 403
    # a person is not a service account
    assert mint(admin, ASMITH).status_code == 404
    # tokens never reach these routes, whatever their scope
    own = admin.call(
        "POST", "/auth/tokens", {"name": "admin", "scope": "admin", "expires_in_days": 7}
    ).json()["secret"]
    bot = TestClient(app, base_url="http://testserver")
    auth = {"Authorization": f"Bearer {own}"}
    path = f"/api/v2/service-accounts/{q(account)}/tokens"
    payload = {"name": "x", "scope": "read", "expires_in_days": 7}
    assert bot.post(path, json=payload, headers=auth).status_code == 403
    assert bot.get(path, headers=auth).status_code == 403
    assert bot.delete(f"{path}/0123456789abcdef", headers=auth).status_code == 403


def test_a_recreated_account_does_not_revive_old_tokens(
    app: FastAPI, directory: MemoryDirectory
) -> None:
    admin = Api(app).login("admin")
    account = create_account(admin)
    grant_helpdesk(admin, account)
    secret = mint(admin, account).json()["secret"]
    auth = {"Authorization": f"Bearer {secret}"}
    bot = TestClient(app, base_url="http://testserver")
    assert bot.get("/api/v2/auth/me", headers=auth).status_code == 200

    # deleted by any path (here straight in the directory), then created again
    directory.delete(account)
    assert bot.get("/api/v2/auth/me", headers=auth).status_code == 401
    assert create_account(admin) == account
    assert bot.get("/api/v2/auth/me", headers=auth).status_code == 401


def test_role_editor_cannot_read_patch_move_or_delete_dsa_as_role(
    app: FastAPI, directory: MemoryDirectory
) -> None:
    admin = Api(app).login("admin")
    account = create_account(admin, "backup-agent")
    grant_helpdesk(admin, account)

    role_acl_dn = f"cn=role-editors,ou=aclroles,{BASE}"
    directory.add(
        role_acl_dn,
        {
            "objectClass": [b"hrcRole"],
            "cn": [b"role-editors"],
            "hrcAclTemplate": [b"0:role/roleGeneric;rwcdm", b"0:role;c"],
        },
    )
    items = admin.call("GET", f"/admin/acl/assignments/{q(BASE)}").json()["assignments"]
    items.append(
        {"index": len(items), "scope": "subtree", "role": role_acl_dn, "members": [ASMITH]}
    )
    assert (
        admin.call("PUT", f"/admin/acl/assignments/{q(BASE)}", {"assignments": items}).status_code
        == 200
    )

    editor = Api(app).login("asmith")
    listed = editor.call("GET", f"/objects/role?base={q(BASE)}&scope=sub")
    assert listed.status_code == 200, listed.text
    assert account not in {item["dn"] for item in listed.json()["items"]}

    assert editor.call("GET", f"/objects/role/{q(account)}").status_code == 404
    assert (
        editor.call(
            "PATCH",
            f"/objects/role/{q(account)}",
            {"tabs": {"main": {"active": True, "values": {"roleOccupant": [ASMITH]}}}},
        ).status_code
        == 404
    )
    assert (
        editor.call("POST", f"/objects/role/{q(account)}/move", {"base": BASE}).status_code == 404
    )
    assert editor.call("DELETE", f"/objects/role/{q(account)}").status_code == 404

    entry = directory.get(account)
    assert entry is not None
    assert entry.texts("roleOccupant") == []
