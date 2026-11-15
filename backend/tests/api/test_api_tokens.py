"""API tokens: creation, Bearer authentication, scopes, type limits, revocation, audit."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.state import AppState
from heracles.api.tokens import RULES
from heracles.auth.api_tokens import parse
from heracles.demo import ADMIN_DN, BASE
from heracles.server import build_demo_app
from heracles_plugins.audit.events import events_for

ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
HELPDESK = f"uid=helpdesk,ou=people,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    def __init__(self, app: FastAPI) -> None:
        self.client = TestClient(app, base_url="http://testserver")
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

    def create(self, **body: Any) -> Any:
        payload: dict[str, Any] = {"name": "ci", "scope": "read", "expires_in_days": 30}
        payload.update(body)
        return self.client.post("/api/v2/auth/tokens", json=payload, headers=self.headers)

    def token(self, **body: Any) -> str:
        r = self.create(**body)
        assert r.status_code == 201, r.text
        return str(r.json()["secret"])


class Bearer:
    """A client that only ever sends the token (no cookie, no CSRF header)."""

    def __init__(self, app: FastAPI, token: str) -> None:
        self.client = TestClient(app, base_url="http://testserver")
        self.auth = {"Authorization": f"Bearer {token}"}

    def request(self, method: str, path: str, body: Any = None) -> Any:
        return self.client.request(method, path, json=body, headers=self.auth)

    def get(self, path: str) -> Any:
        return self.request("GET", path)


@pytest.fixture
def app() -> FastAPI:
    return build_demo_app()


@pytest.fixture
def state(app: FastAPI) -> Iterator[AppState]:
    with TestClient(app):
        yield cast("AppState", app.state.heracles)


def _code(r: Any) -> str:
    body = r.json()
    return str(body["error"]["code"]) if "error" in body else str(body.get("message"))


# -- creation -------------------------------------------------------------------------------------
def test_create_list_and_revoke_own_token(app: FastAPI, state: AppState) -> None:
    me = Api(app).login("helpdesk")
    r = me.create(name="backup script", scope="write", types=["user"])
    assert r.status_code == 201, r.text
    created = r.json()
    assert parse(created["secret"]) is not None
    assert created["owner_dn"] == HELPDESK and created["scope"] == "write"
    assert created["types"] == ["user"]

    listed = me.client.get("/api/v2/auth/tokens").json()
    assert [t["id"] for t in listed] == [created["id"]]
    assert "secret" not in listed[0]

    r = me.client.delete(f"/api/v2/auth/tokens/{created['id']}", headers=me.headers)
    assert r.status_code == 204
    assert Bearer(app, created["secret"]).get("/api/v2/auth/me").status_code == 401


def test_creation_is_validated(app: FastAPI, state: AppState) -> None:
    me = Api(app).login("admin")
    max_days = state.settings.api_tokens.max_lifetime_days
    for body, field in (
        ({"scope": "root"}, "scope"),
        ({"expires_in_days": max_days + 1}, "expires_in_days"),
        ({"types": ["no_such_type"]}, "types"),
        ({"scope": "admin", "types": ["user"]}, "types"),
        ({"name": "   "}, "name"),
    ):
        r = me.create(**body)
        assert r.status_code == 422, (body, r.text)
        assert field in r.json()["error"]["fields"], body


def test_creation_needs_a_recent_sign_in(app: FastAPI, state: AppState) -> None:
    me = Api(app).login("helpdesk")
    state.clock = lambda: time.time() + 3600
    r = me.create()
    assert r.status_code == 403 and _code(r) == "reauth_required"
    assert (
        me.client.post(
            "/api/v2/auth/reauth", json={"password": "heracles"}, headers=me.headers
        ).status_code
        == 200
    )
    assert me.create().status_code == 201


def test_tokens_per_person_are_capped(app: FastAPI, state: AppState) -> None:
    state.settings.api_tokens.max_per_owner = 2
    me = Api(app).login("helpdesk")
    me.token()
    me.token()
    assert me.create().status_code == 422


def test_disabled_tokens_are_refused(app: FastAPI, state: AppState) -> None:
    me = Api(app).login("helpdesk")
    token = me.token()
    state.settings.api_tokens.enabled = False
    assert me.create().status_code == 404
    assert Bearer(app, token).get("/api/v2/auth/me").status_code == 401


def test_portal_users_cannot_create_tokens(app: FastAPI, state: AppState) -> None:
    r = Api(app).login("asmith").create()
    assert r.status_code == 403 and "console" in r.json()["error"]["message"]
    assert state.api_tokens.list_all() == []


# -- authentication -------------------------------------------------------------------------------
def test_bearer_token_acts_as_its_owner(app: FastAPI, state: AppState) -> None:
    token = Api(app).login("helpdesk").token()
    bearer = Bearer(app, token)
    me = bearer.get("/api/v2/auth/me")
    assert me.status_code == 200 and me.json()["dn"] == HELPDESK
    assert bearer.get("/api/v2/objects/user").status_code == 200
    (stored,) = state.api_tokens.list_for_owner(HELPDESK)
    assert stored.last_used_at is not None and stored.last_used_ip


def test_invalid_tokens_are_401_without_falling_back_to_the_cookie(
    app: FastAPI, state: AppState
) -> None:
    me = Api(app).login("helpdesk")
    token = me.token()
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    for value in ("hrc_garbage", forged, "hrc_0123456789abcdef_" + "x" * 43):
        # the same client still holds a valid session cookie
        r = me.client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {value}"})
        assert r.status_code == 401, value
        assert r.headers["WWW-Authenticate"].startswith("Bearer")
    # Basic, or a Bearer credential that is not ours (a proxy's): the cookie session applies
    for header in ("Basic Zm9vOmJhcg==", "Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig"):
        r = me.client.get("/api/v2/auth/me", headers={"Authorization": header})
        assert r.status_code == 200, header


def test_bearer_requests_need_no_csrf_but_cookie_requests_still_do(
    app: FastAPI, state: AppState
) -> None:
    me = Api(app).login("admin")
    token = me.token(scope="write")
    body = {"tabs": {"main": {"values": {"description": "set by a script"}}}}
    r = Bearer(app, token).request("PATCH", f"/api/v2/objects/user/{q(ASMITH)}", body)
    assert r.status_code == 200, r.text
    r = me.client.patch(f"/api/v2/objects/user/{q(ASMITH)}", json=body)  # no CSRF header
    assert r.status_code == 403


def test_expired_token_is_refused(app: FastAPI, state: AppState) -> None:
    token = Api(app).login("helpdesk").token(expires_in_days=1)
    state.clock = lambda: time.time() + 2 * 86_400
    r = Bearer(app, token).get("/api/v2/auth/me")
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]


def test_token_of_a_locked_owner_is_refused(app: FastAPI, state: AppState) -> None:
    token = Api(app).login("helpdesk").token()
    admin = Api(app).login("admin")
    assert (
        admin.client.post(f"/api/v2/users/{q(HELPDESK)}/lock", headers=admin.headers).status_code
        == 200
    )
    assert Bearer(app, token).get("/api/v2/auth/me").status_code == 401
    assert (
        admin.client.post(f"/api/v2/users/{q(HELPDESK)}/unlock", headers=admin.headers).status_code
        == 200
    )
    assert Bearer(app, token).get("/api/v2/auth/me").status_code == 200


# -- scopes ---------------------------------------------------------------------------------------
def test_read_token_cannot_write(app: FastAPI, state: AppState) -> None:
    token = Api(app).login("helpdesk").token(scope="read")
    body = {"tabs": {"main": {"values": {"description": "nope"}}}}
    r = Bearer(app, token).request("PATCH", f"/api/v2/objects/user/{q(ASMITH)}", body)
    assert r.status_code == 403 and _code(r) == "token_scope"


def test_administration_needs_the_admin_scope(app: FastAPI, state: AppState) -> None:
    admin = Api(app).login("admin")
    write = Bearer(app, admin.token(scope="write"))
    full = Bearer(app, admin.token(scope="admin"))
    for path in ("/api/v2/admin/config", "/api/v2/admin/hooks", "/api/v2/admin/plugins"):
        assert write.get(path).status_code == 403, path
        assert full.get(path).status_code == 200, path


def test_admin_scope_does_not_exceed_the_owner_acl(app: FastAPI, state: AppState) -> None:
    token = Api(app).login("helpdesk").token(scope="admin")
    r = Bearer(app, token).get("/api/v2/admin/config")
    assert r.status_code == 403 and _code(r) != "token_scope"


def test_account_security_is_never_reachable_with_a_token(app: FastAPI, state: AppState) -> None:
    admin = Api(app).login("admin")
    bearer = Bearer(app, admin.token(scope="admin"))
    for method, path in (
        ("GET", "/api/v2/auth/tokens"),
        ("POST", "/api/v2/auth/tokens"),
        ("GET", "/api/v2/tokens"),
        ("GET", "/api/v2/auth/sessions"),
        ("GET", "/api/v2/auth/totp"),
        ("GET", "/api/v2/auth/csrf"),
        ("POST", "/api/v2/auth/logout"),
        ("POST", "/api/v2/auth/reauth"),
        ("GET", f"/api/v2/users/{q(ASMITH)}/second-factors"),
        ("DELETE", f"/api/v2/users/{q(ASMITH)}/sessions"),
        ("GET", "/api/v1/token"),
        ("POST", "/api/v1/logout"),
    ):
        r = bearer.request(method, path, {} if method == "POST" else None)
        assert r.status_code == 403, (method, path, r.status_code)


def test_step_up_is_never_satisfied_by_a_token(app: FastAPI, state: AppState) -> None:
    token = Api(app).login("helpdesk").token(scope="write")
    body = {"tabs": {"main": {"active": True, "values": {"userPassword": "Another-pass-1"}}}}
    r = Bearer(app, token).request("PATCH", f"/api/v2/objects/user/{q(HELPDESK)}", body)
    assert r.status_code == 403 and _code(r) == "token_scope"
    r = Bearer(app, token).request(
        "PUT",
        f"/api/v1/objects/user/{q(HELPDESK)}/user/userPassword",
        {"values": ["Another-pass-1"]},
    )
    assert r.status_code == 403, r.text
    assert "interactive sign-in" in r.json()["message"], r.text


def test_type_limited_token(app: FastAPI, state: AppState) -> None:
    bearer = Bearer(app, Api(app).login("admin").token(scope="write", types=["user"]))
    assert bearer.get("/api/v2/objects/user").status_code == 200
    assert bearer.get("/api/v2/types/user").status_code == 200
    assert bearer.get("/api/v2/types").status_code == 200
    assert bearer.get("/api/v2/auth/me").status_code == 200
    assert bearer.request("POST", f"/api/v2/users/{q(ASMITH)}/lock").status_code == 200
    for path in ("/api/v2/objects/group", "/api/v2/types/group", "/api/v2/tree", "/api/v2/audit"):
        r = bearer.get(path)
        assert r.status_code == 403 and _code(r) == "token_scope", path


# -- API v1 ---------------------------------------------------------------------------------------
def test_api_v1_accepts_tokens(app: FastAPI, state: AppState) -> None:
    bearer = Bearer(app, Api(app).login("helpdesk").token(scope="read"))
    assert bearer.get("/api/v1/objects/user").status_code == 200
    assert bearer.get(f"/api/v1/userlock/{q(ASMITH)}").status_code == 200
    r = bearer.request("PUT", f"/api/v1/userlock/{q(ASMITH)}", True)
    assert r.status_code == 403 and "scope" in r.json()["message"]


# -- revocation -----------------------------------------------------------------------------------
def test_administrator_lists_and_revokes_any_token(app: FastAPI, state: AppState) -> None:
    mine = Api(app).login("helpdesk")
    secret = mine.token(name="laptop")
    assert mine.client.get("/api/v2/tokens").status_code == 403

    admin = Api(app).login("admin")
    (token,) = [t for t in admin.client.get("/api/v2/tokens").json() if t["owner_dn"] == HELPDESK]
    assert token["name"] == "laptop" and "secret" not in token
    mine_only = admin.client.get("/api/v2/tokens", params={"owner": HELPDESK}).json()
    assert [t["id"] for t in mine_only] == [token["id"]]
    r = admin.client.delete(f"/api/v2/tokens/{token['id']}", headers=admin.headers)
    assert r.status_code == 204
    assert Bearer(app, secret).get("/api/v2/auth/me").status_code == 401


def test_someone_elses_token_cannot_be_revoked_by_its_id(app: FastAPI, state: AppState) -> None:
    Api(app).login("helpdesk").token()
    (token,) = state.api_tokens.list_for_owner(HELPDESK)
    other = Api(app).login("admin")
    r = other.client.delete(f"/api/v2/auth/tokens/{token.id}", headers=other.headers)
    assert r.status_code == 404


def test_sign_out_everywhere_revokes_tokens(app: FastAPI, state: AppState) -> None:
    secret = Api(app).login("helpdesk").token()
    admin = Api(app).login("admin")
    r = admin.client.delete(f"/api/v2/users/{q(HELPDESK)}/sessions", headers=admin.headers)
    assert r.status_code == 200 and r.json()["tokens_revoked"] == 1
    assert Bearer(app, secret).get("/api/v2/auth/me").status_code == 401


# -- audit ----------------------------------------------------------------------------------------
def test_changes_made_with_a_token_name_it_in_the_audit_log(app: FastAPI, state: AppState) -> None:
    me = Api(app).login("admin")
    r = me.create(scope="write")
    token_id, secret = r.json()["id"], r.json()["secret"]
    body = {"tabs": {"main": {"values": {"description": "via token"}}}}
    r = Bearer(app, secret).request("PATCH", f"/api/v2/objects/user/{q(ASMITH)}", body)
    assert r.status_code == 200, r.text
    events = events_for(state.directories["main"], ASMITH)
    modify = [e for e in events if e.text("hrcAuditAction") == "modify"]
    assert modify, [e.text("hrcAuditAction") for e in events]
    admin_events = events_for(state.directories["main"], ADMIN_DN)
    created = [e for e in admin_events if e.text("hrcAuditAction") == "api_token"]
    assert created and created[0].text("hrcAuditAuthorDN") == ADMIN_DN
    assert modify[0].texts("hrcAuditAttributes")[0] == f"via: api token {token_id}"


# -- route table ----------------------------------------------------------------------------------
def test_rules_never_open_account_security() -> None:
    for rule in RULES:
        for path in ("/api/v2/auth/tokens", "/api/v2/auth/sessions", "/api/v2/tokens"):
            assert not rule.pattern.match(path), (rule, path)


def test_delegated_helpdesk_revokes_the_tokens_of_accounts_it_may_lock(
    app: FastAPI, state: AppState
) -> None:
    from heracles.auth import api_tokens as tokens_mod

    made = tokens_mod.generate(
        owner_dn=ASMITH,
        directory_id="main",
        name="from before",
        scope="read",
        types=(),
        expires_at=time.time() + 3600,
        created_by=ASMITH,
        now=time.time(),
    )
    state.api_tokens.add(made.token)
    secret = made.secret
    helpdesk = Api(app).login("helpdesk")
    assert helpdesk.client.get("/api/v2/tokens").status_code == 403
    listed = helpdesk.client.get("/api/v2/tokens", params={"owner": ASMITH})
    assert listed.status_code == 200, listed.text
    (token,) = listed.json()
    r = helpdesk.client.delete(f"/api/v2/tokens/{token['id']}", headers=helpdesk.headers)
    assert r.status_code == 204
    assert Bearer(app, secret).get("/api/v2/auth/me").status_code == 401
    # someone without that right gets nothing
    Api(app).login("helpdesk").token()
    (theirs,) = state.api_tokens.list_all()
    plain = Api(app).login("asmith")
    r = plain.client.delete(f"/api/v2/tokens/{theirs.id}", headers=plain.headers)
    assert r.status_code == 404


# -- what a scope reaches through the object layer -------------------------------------------------
def test_write_token_cannot_change_administration_objects(app: FastAPI, state: AppState) -> None:
    admin = Api(app).login("admin")
    write = Bearer(app, admin.token(scope="write"))
    full = Bearer(app, admin.token(scope="admin"))
    roles = write.get("/api/v2/objects/acl_role")
    assert roles.status_code == 200, roles.text  # reading is fine
    body = {"base": BASE, "tabs": {"main": {"values": {"cn": "token-made-role"}}}}
    r = write.request("POST", "/api/v2/objects/acl_role", body)
    assert r.status_code == 403, r.text
    assert full.request("POST", "/api/v2/objects/acl_role", body).status_code != 403

    task = {"base": BASE, "tabs": {"main": {"values": {"cn": "token-made-task"}}}}
    assert write.request("POST", "/api/v2/objects/extractor_task", task).status_code == 403

    paris = f"ou=paris,{BASE}"
    acl: dict[str, Any] = {"tabs": {"acl": {"active": True, "values": {}}}}
    r = write.request("PATCH", f"/api/v2/objects/department/{q(paris)}", acl)
    assert r.status_code == 403, r.text


def test_read_token_is_read_only_in_the_object_layer(app: FastAPI, state: AppState) -> None:
    from heracles.api.tokens import rights_cap
    from heracles.auth.sessions import Session

    cache: dict[str, Any] = {"api_token": "i", "api_token.scope": "read"}
    session = Session("x", ASMITH, "main", 0.0, 0.0, cache=cache)
    cap = rights_cap(session, app.state.domain.registry)
    assert cap is not None
    rights = cap("user/user")
    assert rights.read and not (rights.write or rights.create or rights.delete or rights.move)


def test_type_limit_holds_against_a_dn_of_another_type(app: FastAPI, state: AppState) -> None:
    admin = Api(app).login("admin")
    bearer = Bearer(app, admin.token(scope="write", types=["user"]))
    groups = admin.client.get("/api/v2/objects/group").json()
    items = cast("list[dict[str, Any]]", groups["items"] if isinstance(groups, dict) else groups)
    group_dn = str(items[0]["dn"])
    r = bearer.get(f"/api/v2/objects/user/{q(group_dn)}")
    assert r.status_code in (403, 404), r.text
    body = {"tabs": {"main": {"values": {"description": "crossed types"}}}}
    r = bearer.request("PATCH", f"/api/v2/objects/user/{q(group_dn)}", body)
    assert r.status_code in (403, 404, 422), r.text
    entry = state.directories["main"].get(group_dn, ["description"])
    assert entry is not None and entry.text("description") != "crossed types"


def test_unverified_token_never_marks_audit_events() -> None:
    from fastapi import FastAPI as Plain

    from heracles.api.middleware import install_middleware
    from heracles.core.audit import AUDIT_VIA

    plain = Plain()
    install_middleware(plain)

    @plain.get("/public")
    def public() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {"via": AUDIT_VIA.get()}

    client = TestClient(plain)
    forged = {"Authorization": "Bearer hrc_0123456789abcdef_" + "x" * 43}
    assert client.get("/public", headers=forged).json() == {"via": [""]}


# -- the whole route table -------------------------------------------------------------------------
def test_routes_reachable_with_a_token_are_the_listed_ones(app: FastAPI, state: AppState) -> None:
    """Every route a token may reach, by scope. A new route (a plugin's, an admin screen's) shows
    up here and must be decided on: add it to this list, or leave it refused."""
    import re as _re

    def templates() -> list[tuple[str, str]]:
        paths = cast("dict[str, dict[str, object]]", app.openapi()["paths"])
        return [(m.upper(), path) for path, ops in paths.items() for m in ops]

    reachable: dict[str, list[str]] = {"read": [], "write": [], "admin": []}
    for method, path in sorted(set(templates())):
        if not path.startswith(("/api/v", "/scim/")):
            continue
        rule = next((r for r in RULES if method in r.methods and r.pattern.match(path)), None)
        if rule is not None:
            reachable[rule.scope].append(f"{method} {path}")
    assert not any(
        _re.search(r"/auth/(?!me)", e)
        for e in reachable["read"] + reachable["write"] + reachable["admin"]
    )
    assert reachable == EXPECTED_ROUTES, reachable


EXPECTED_ROUTES: dict[str, list[str]] = {
    "read": [
        "GET /api/v1/objects/{type}",
        "GET /api/v1/objects/{type}/{dn}",
        "GET /api/v1/objects/{type}/{dn}/templatefields",
        "GET /api/v1/objects/{type}/{dn}/{tab}",
        "GET /api/v1/objects/{type}/{dn}/{tab}/{attribute}",
        "GET /api/v1/types",
        "GET /api/v1/types/{type}",
        "GET /api/v1/types/{type}/{tab}",
        "GET /api/v1/userlock/{dn}",
        "GET /api/v2/audit",
        "GET /api/v2/auth/me",
        "GET /api/v2/auth/me/groups",
        "GET /api/v2/dashboard",
        "GET /api/v2/me/applications",
        "GET /api/v2/objects/{type_name}",
        "GET /api/v2/objects/{type_name}/{dn}",
        "GET /api/v2/objects/{type_name}/{dn}/ldif",
        "GET /api/v2/objects/{type_name}/{dn}/references",
        "GET /api/v2/objects/{type_name}/{dn}/snapshots",
        "GET /api/v2/snapshots/deleted",
        "GET /api/v2/status",
        "GET /api/v2/tree",
        "GET /api/v2/types",
        "GET /api/v2/types/{type_name}",
        "GET /api/v2/types/{type_name}/templates",
        "GET /api/v2/types/{type_name}/templates/{dn}",
        "GET /api/v2/types/{type_name}/templates/{dn}/fields",
        "GET /scim/v2/Groups",
        "GET /scim/v2/Groups/{resource_id}",
        "GET /scim/v2/ResourceTypes",
        "GET /scim/v2/ResourceTypes/{name}",
        "GET /scim/v2/Schemas",
        "GET /scim/v2/Schemas/{urn}",
        "GET /scim/v2/ServiceProviderConfig",
        "GET /scim/v2/Users",
        "GET /scim/v2/Users/{resource_id}",
        "POST /api/v2/types/{type_name}/templates/{dn}/preview",
        "POST /scim/v2/Groups/.search",
        "POST /scim/v2/Users/.search",
    ],
    "write": [
        "DELETE /api/v1/objects/{type}/{dn}",
        "DELETE /api/v1/objects/{type}/{dn}/{tab}",
        "DELETE /api/v1/objects/{type}/{dn}/{tab}/{attribute}",
        "DELETE /api/v1/objects/{type}/{dn}/{tab}/{attribute}/values",
        "DELETE /api/v2/objects/{type_name}/{dn}",
        "DELETE /api/v2/objects/{type_name}/{dn}/lock",
        "DELETE /api/v2/snapshots/{snapshot_id}",
        "DELETE /scim/v2/Groups/{resource_id}",
        "DELETE /scim/v2/Users/{resource_id}",
        "PATCH /api/v1/objects/{type}/{dn}",
        "PATCH /api/v1/objects/{type}/{dn}/{tab}",
        "PATCH /api/v1/objects/{type}/{dn}/{tab}/{attribute}/values",
        "PATCH /api/v2/objects/{type_name}/_bulk",
        "PATCH /api/v2/objects/{type_name}/{dn}",
        "PATCH /scim/v2/Groups/{resource_id}",
        "PATCH /scim/v2/Users/{resource_id}",
        "POST /api/v1/archive/{type}/{dn}",
        "POST /api/v1/objects/{type}",
        "POST /api/v2/archive/{type_name}/{dn}",
        "POST /api/v2/objects/{type_name}",
        "POST /api/v2/objects/{type_name}/_bulk/attributes",
        "POST /api/v2/objects/{type_name}/{dn}/copy",
        "POST /api/v2/objects/{type_name}/{dn}/lock",
        "POST /api/v2/objects/{type_name}/{dn}/move",
        "POST /api/v2/objects/{type_name}/{dn}/snapshots",
        "POST /api/v2/snapshots/{snapshot_id}/restore",
        "POST /api/v2/users/{dn}/lock",
        "POST /api/v2/users/{dn}/unlock",
        "POST /scim/v2/Groups",
        "POST /scim/v2/Users",
        "PUT /api/v1/objects/{type}/{dn}/{tab}/{attribute}",
        "PUT /api/v1/userlock/{dn}",
        "PUT /scim/v2/Groups/{resource_id}",
        "PUT /scim/v2/Users/{resource_id}",
    ],
    "admin": [
        "DELETE /api/v2/admin/acl/roles/{dn}",
        "DELETE /api/v2/types/{type_name}/templates/{dn}",
        "GET /api/v2/admin/acl/assignments",
        "GET /api/v2/admin/acl/assignments/{dn}",
        "GET /api/v2/admin/acl/catalog",
        "GET /api/v2/admin/acl/roles",
        "GET /api/v2/admin/acl/roles/{dn}",
        "GET /api/v2/admin/capabilities",
        "GET /api/v2/admin/checks",
        "GET /api/v2/admin/config",
        "GET /api/v2/admin/hooks",
        "GET /api/v2/admin/plugins",
        "GET /api/v2/admin/tasks",
        "GET /api/v2/admin/tasks/runs",
        "GET /api/v2/csv/{type_name}/fields",
        "GET /api/v2/ldif/export",
        "PATCH /api/v2/admin/plugins/{name}",
        "PATCH /api/v2/types/{type_name}/templates/{dn}",
        "POST /api/v2/admin/acl/check",
        "POST /api/v2/admin/acl/roles",
        "POST /api/v2/admin/checks/{check_id}/fix",
        "POST /api/v2/admin/tasks/{dn}/retry",
        "POST /api/v2/admin/tasks/{dn}/run",
        "POST /api/v2/csv/parse",
        "POST /api/v2/csv/{type_name}/import",
        "POST /api/v2/invitations/send",
        "POST /api/v2/ldif/import",
        "POST /api/v2/types/{type_name}/templates",
        "PUT /api/v2/admin/acl/assignments/{dn}",
        "PUT /api/v2/admin/acl/roles/{dn}",
        "PUT /api/v2/admin/config",
        "PUT /api/v2/admin/hooks",
    ],
}
