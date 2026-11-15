"""SCIM end to end: the real router and service over the demo directory, with API tokens.

Scenarios follow RFC 7644 (create, read, list with filters and paging, replace, patch,
delete, ETags, errors) plus what Heracles adds: the token's scope and owner rights, the
account lock behind ``active``, stable ids across renames and the audit trail.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.state import AppState
from heracles.demo import ADMIN_DN, BASE
from heracles.scim.schemas import (
    ERROR_SCHEMA,
    GROUP_SCHEMA,
    LIST_RESPONSE,
    PATCH_OP,
    SERVICE_PROVIDER_CONFIG_SCHEMA,
    USER_SCHEMA,
)
from heracles.server import build_demo_app
from heracles_plugins.audit.events import events_for

SCIM = "/scim/v2"
JSON_SCIM = {"Content-Type": "application/scim+json"}


class Console:
    """A signed-in console user able to mint tokens."""

    def __init__(self, app: FastAPI, username: str) -> None:
        self.client = TestClient(app, base_url="http://testserver")
        csrf = self.client.get("/api/v2/auth/csrf").json()["token"]
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": username, "password": "heracles"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200, r.text
        self.csrf = self.client.get("/api/v2/auth/csrf").json()["token"]

    def token(self, scope: str = "write", types: list[str] | None = None) -> tuple[str, str]:
        r = self.client.post(
            "/api/v2/auth/tokens",
            json={
                "name": "provisioning",
                "scope": scope,
                "types": types or [],
                "expires_in_days": 7,
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        assert r.status_code == 201, r.text
        return str(r.json()["id"]), str(r.json()["secret"])


class Scim:
    def __init__(self, app: FastAPI, secret: str) -> None:
        self.client = TestClient(app, base_url="http://testserver")
        self.auth = {"Authorization": f"Bearer {secret}"}

    def call(self, method: str, path: str, body: Any = None, **headers: str) -> Any:
        merged = {**self.auth, **(JSON_SCIM if body is not None else {}), **headers}
        return self.client.request(
            method, SCIM + path, content=None if body is None else _json(body), headers=merged
        )


def _json(body: Any) -> bytes:
    import json

    return json.dumps(body).encode()


@pytest.fixture
def app() -> FastAPI:
    return build_demo_app()


@pytest.fixture
def state(app: FastAPI) -> Iterator[AppState]:
    with TestClient(app):
        yield cast("AppState", app.state.heracles)


@pytest.fixture
def admin(app: FastAPI, state: AppState) -> tuple[str, Scim]:
    token_id, secret = Console(app, "admin").token("write")
    return token_id, Scim(app, secret)


def _new_user(uid: str = "scim.jdoe") -> dict[str, Any]:
    return {
        "schemas": [USER_SCHEMA],
        "userName": uid,
        "name": {"familyName": "Doe", "givenName": "Jane"},
        "displayName": "Jane Doe",
        "emails": [{"value": f"{uid}@example.org", "type": "work", "primary": True}],
        "password": "Initial-pass-1",
    }


def _create(scim: Scim, uid: str = "scim.jdoe") -> dict[str, Any]:
    r = scim.call("POST", "/Users", _new_user(uid))
    assert r.status_code == 201, r.text
    return cast("dict[str, Any]", r.json())


def _patch(*ops: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": [PATCH_OP], "Operations": list(ops)}


# -- discovery and authentication -----------------------------------------------------------------
def test_discovery_needs_a_token_and_describes_the_service(
    app: FastAPI, admin: tuple[str, Scim]
) -> None:
    _, scim = admin
    r = scim.call("GET", "/ServiceProviderConfig")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/scim+json")
    assert SERVICE_PROVIDER_CONFIG_SCHEMA in r.json()["schemas"]
    assert r.json()["patch"]["supported"] is True
    anonymous = TestClient(app).get(SCIM + "/Users")
    assert anonymous.status_code == 401 and ERROR_SCHEMA in anonymous.json()["schemas"]
    assert anonymous.headers["WWW-Authenticate"].startswith("Bearer")


def test_a_session_cookie_never_reaches_scim(app: FastAPI, state: AppState) -> None:
    console = Console(app, "admin")
    r = console.client.get(SCIM + "/Users")
    assert r.status_code == 401


# -- users ----------------------------------------------------------------------------------------
def test_user_lifecycle(admin: tuple[str, Scim], state: AppState) -> None:
    _, scim = admin
    created = _create(scim)
    rid = created["id"]
    assert created["userName"] == "scim.jdoe"
    assert created["meta"]["resourceType"] == "User"
    assert created["meta"]["location"].endswith(f"/scim/v2/Users/{rid}")
    assert "password" not in created and created["active"] is True

    got = scim.call("GET", f"/Users/{rid}")
    assert got.status_code == 200 and got.json()["emails"][0]["value"] == "scim.jdoe@example.org"
    etag = got.headers["ETag"]
    assert scim.call("GET", f"/Users/{rid}", **{"If-None-Match": etag}).status_code == 304

    dup = scim.call("POST", "/Users", _new_user())
    assert dup.status_code == 409 and dup.json()["scimType"] == "uniqueness"

    stale = scim.call(
        "PATCH",
        f"/Users/{rid}",
        _patch({"op": "replace", "path": "displayName", "value": "J."}),
        **{"If-Match": 'W/"not-the-version"'},
    )
    assert stale.status_code == 412

    patched = scim.call(
        "PATCH", f"/Users/{rid}", _patch({"op": "replace", "path": "displayName", "value": "J."})
    )
    assert patched.status_code == 200 and patched.json()["displayName"] == "J."
    assert patched.headers["ETag"] != etag

    assert scim.call("DELETE", f"/Users/{rid}").status_code == 204
    assert scim.call("GET", f"/Users/{rid}").status_code == 404


def test_id_survives_a_rename(admin: tuple[str, Scim], state: AppState) -> None:
    _, scim = admin
    rid = _create(scim)["id"]
    r = scim.call(
        "PATCH", f"/Users/{rid}", _patch({"op": "replace", "path": "userName", "value": "jdoe2"})
    )
    assert r.status_code == 200, r.text
    again = scim.call("GET", f"/Users/{rid}")
    assert again.status_code == 200 and again.json()["userName"] == "jdoe2"


def test_active_false_locks_the_account(admin: tuple[str, Scim], state: AppState) -> None:
    _, scim = admin
    rid = _create(scim)["id"]
    r = scim.call(
        "PATCH", f"/Users/{rid}", _patch({"op": "replace", "path": "active", "value": False})
    )
    assert r.status_code == 200 and r.json()["active"] is False
    (entry,) = list(
        state.directories["main"].search(BASE, "(uid=scim.jdoe)", attrs=["userPassword"])
    )
    assert (entry.text("userPassword") or "").split("}", 1)[1].startswith("!")
    r = scim.call(
        "PATCH", f"/Users/{rid}", _patch({"op": "replace", "path": "active", "value": True})
    )
    assert r.json()["active"] is True


def test_put_replaces_mapped_attributes_only(admin: tuple[str, Scim], state: AppState) -> None:
    _, scim = admin
    created = _create(scim)
    rid = created["id"]
    directory = state.directories["main"]
    (entry,) = list(directory.search(BASE, "(uid=scim.jdoe)", attrs=["uid"]))
    from heracles.ldap.client import Modification

    directory.modify(entry.dn, [Modification("replace", "roomNumber", [b"B12"])])
    body = {
        "schemas": [USER_SCHEMA],
        "userName": "scim.jdoe",
        "name": {"familyName": "Doe", "givenName": "Janet"},
    }
    r = scim.call("PUT", f"/Users/{rid}", body)
    assert r.status_code == 200, r.text
    assert r.json()["name"]["givenName"] == "Janet" and "displayName" not in r.json()
    after = directory.get(entry.dn, ["roomNumber", "displayName"])
    assert after is not None and after.text("roomNumber") == "B12"
    assert after.text("displayName") is None


def test_list_filter_paging_and_projection(admin: tuple[str, Scim], state: AppState) -> None:
    _, scim = admin
    for i in range(3):
        _create(scim, f"scim.page{i}")
    q = quote('userName sw "scim.page"')
    r = scim.call("GET", f"/Users?filter={q}&count=2&startIndex=1&attributes=userName")
    body = r.json()
    assert r.status_code == 200 and LIST_RESPONSE in body["schemas"]
    assert body["totalResults"] == 3 and body["itemsPerPage"] == 2 and body["startIndex"] == 1
    assert all(set(res) <= {"id", "schemas", "userName"} for res in body["Resources"])
    page2 = scim.call("GET", f"/Users?filter={q}&count=2&startIndex=3").json()
    assert len(page2["Resources"]) == 1
    eq = scim.call("GET", "/Users?filter=" + quote('userName eq "scim.page1"')).json()
    assert [res["userName"] for res in eq["Resources"]] == ["scim.page1"]
    bad = scim.call("GET", "/Users?filter=" + quote('nickName eq "x"'))
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidFilter"
    syntax = scim.call("GET", "/Users?filter=" + quote("userName eq"))
    assert syntax.status_code == 400 and syntax.json()["scimType"] == "invalidFilter"


# -- groups ---------------------------------------------------------------------------------------
def test_group_lifecycle(admin: tuple[str, Scim], state: AppState) -> None:
    _, scim = admin
    a = _create(scim, "scim.member.a")["id"]
    b = _create(scim, "scim.member.b")["id"]
    empty = scim.call("POST", "/Groups", {"schemas": [GROUP_SCHEMA], "displayName": "scim-empty"})
    assert empty.status_code == 400 and empty.json()["scimType"] == "invalidValue"

    r = scim.call(
        "POST",
        "/Groups",
        {"schemas": [GROUP_SCHEMA], "displayName": "scim-team", "members": [{"value": a}]},
    )
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    r = scim.call(
        "PATCH", f"/Groups/{gid}", _patch({"op": "add", "path": "members", "value": [{"value": b}]})
    )
    assert sorted(m["value"] for m in r.json()["members"]) == sorted([a, b])
    path = f'members[value eq "{a}"]'
    r = scim.call("PATCH", f"/Groups/{gid}", _patch({"op": "remove", "path": path}))
    assert [m["value"] for m in r.json()["members"]] == [b]
    last = scim.call(
        "PATCH", f"/Groups/{gid}", _patch({"op": "remove", "path": f'members[value eq "{b}"]'})
    )
    assert last.status_code == 400
    user = scim.call("GET", f"/Users/{b}").json()
    assert gid in [g["value"] for g in user.get("groups", [])]
    assert scim.call("DELETE", f"/Groups/{gid}").status_code == 204


# -- scopes, rights, audit ------------------------------------------------------------------------
def test_token_scope_and_type_limits_apply(app: FastAPI, admin: tuple[str, Scim]) -> None:
    console = Console(app, "admin")
    _, read_secret = console.token("read")
    reader = Scim(app, read_secret)
    assert reader.call("GET", "/Users").status_code == 200
    r = reader.call("POST", "/Users", _new_user("scim.nope"))
    assert r.status_code == 403 and ERROR_SCHEMA in r.json()["schemas"]
    _, groups_secret = console.token("write", ["group"])
    groups_only = Scim(app, groups_secret)
    assert groups_only.call("GET", "/Groups").status_code == 200
    assert groups_only.call("GET", "/Users").status_code == 403


def test_owner_acl_limits_what_scim_sees(app: FastAPI, state: AppState) -> None:
    _, secret = Console(app, "helpdesk").token("write")
    helpdesk = Scim(app, secret)
    r = helpdesk.call("POST", "/Users", _new_user("scim.helpdesk"))
    assert r.status_code == 403, r.text


def test_changes_are_audited_with_the_token(admin: tuple[str, Scim], state: AppState) -> None:
    token_id, scim = admin
    created = _create(scim, "scim.audited")
    directory = state.directories["main"]
    (entry,) = list(directory.search(BASE, "(uid=scim.audited)", attrs=["uid"]))
    events = events_for(directory, entry.dn)
    create = [e for e in events if e.text("hrcAuditAction") == "create"]
    assert create, [e.text("hrcAuditAction") for e in events]
    assert create[0].text("hrcAuditAuthorDN") == ADMIN_DN
    assert create[0].texts("hrcAuditAttributes")[0] == f"via: api token {token_id}"
    assert created["id"]


def test_delete_with_a_write_token_still_archives(admin: tuple[str, Scim], state: AppState) -> None:
    from heracles_plugins.archive.service import find_archives

    _, scim = admin
    rid = _create(scim, "scim.archived")["id"]
    assert scim.call("DELETE", f"/Users/{rid}").status_code == 204
    assert find_archives(state.directories["main"], "user", {"uid": "scim.archived"})


def test_own_password_cannot_be_changed_with_a_token(admin: tuple[str, Scim]) -> None:
    _, scim = admin
    me = scim.call("GET", "/Users?filter=" + quote('userName eq "admin"')).json()["Resources"][0]
    r = scim.call(
        "PATCH",
        f"/Users/{me['id']}",
        _patch({"op": "replace", "path": "password", "value": "Another-pass-1"}),
    )
    assert r.status_code == 403 and ERROR_SCHEMA in r.json()["schemas"]
