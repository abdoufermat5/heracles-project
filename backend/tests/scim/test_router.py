"""The SCIM HTTP surface, against a fake service (the real one is tested end to end)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.state import AppState
from heracles.scim import filter as scim_filter
from heracles.scim import router as scim_router
from heracles.scim.errors import MUTABILITY, UNIQUENESS, ScimError, not_found
from heracles.scim.filter import Compare, Filter
from heracles.scim.patch import PatchOp
from heracles.scim.schemas import (
    ENTERPRISE_USER_SCHEMA,
    ERROR_SCHEMA,
    GROUP_SCHEMA,
    LIST_RESPONSE,
    PATCH_OP,
    SCHEMA_SCHEMA,
    SEARCH_REQUEST,
    USER_SCHEMA,
)
from heracles.scim.service import Page
from heracles.server import build_demo_app

BASE = "http://testserver/scim/v2"
SCIM = "application/scim+json"


def _version(resource: Mapping[str, Any]) -> str:
    body = {k: v for k, v in resource.items() if k != "meta"}
    return 'W/"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16] + '"'


class FakeOps:
    """In-memory resources in SCIM shape; records the calls the router makes."""

    def __init__(self, kind: str, schema: str) -> None:
        self.kind = kind
        self.schema = schema
        self.items: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.counter = 0

    def _stamp(self, resource: dict[str, Any], rid: str) -> dict[str, Any]:
        out = {k: v for k, v in resource.items() if k not in ("id", "meta")}
        out["schemas"] = [self.schema]
        out["id"] = rid
        out["meta"] = {
            "resourceType": self.kind,
            "location": f"{BASE}/{self.kind}s/{rid}",
            "version": _version(out),
        }
        return out

    def add(self, **fields: Any) -> dict[str, Any]:
        self.counter += 1
        rid = f"id-{self.counter}"
        self.items[rid] = self._stamp(fields, rid)
        return self.items[rid]

    def get(self, resource_id: str) -> dict[str, Any]:
        self.calls.append(("get", resource_id))
        if resource_id not in self.items:
            raise not_found()
        return self.items[resource_id]

    def search(
        self,
        flt: Filter | None,
        *,
        start_index: int = 1,
        count: int | None = None,
        sort_by: str | None = None,
        descending: bool = False,
    ) -> Page:
        self.calls.append(("search", (flt, start_index, count, sort_by, descending)))
        rows = list(self.items.values())
        total = len(rows)
        rows = rows[start_index - 1 :]
        if count is not None:
            rows = rows[:count]
        return Page(rows, total, start_index)

    def create(self, resource: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", resource))
        if resource.get("userName") == "taken":
            raise ScimError(409, "userName is already used", UNIQUENESS)
        return self.add(**resource)

    def replace(self, resource_id: str, resource: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("replace", (resource_id, resource)))
        self.get(resource_id)
        self.items[resource_id] = self._stamp(resource, resource_id)
        return self.items[resource_id]

    def patch(self, resource_id: str, ops: list[PatchOp]) -> dict[str, Any]:
        self.calls.append(("patch", (resource_id, ops)))
        current = self.get(resource_id)
        merged = dict(current)
        for op in ops:
            if op.path in ("id", "meta"):
                raise ScimError(400, "read-only", MUTABILITY)
            if op.path and op.op != "remove":
                merged[op.path] = op.value
        self.items[resource_id] = self._stamp(merged, resource_id)
        return self.items[resource_id]

    def delete(self, resource_id: str) -> None:
        self.calls.append(("delete", resource_id))
        self.get(resource_id)
        del self.items[resource_id]


class FakeService:
    def __init__(self) -> None:
        self.users = FakeOps("User", USER_SCHEMA)
        self.groups = FakeOps("Group", GROUP_SCHEMA)


# -- harness --------------------------------------------------------------------------------------
class Harness:
    def __init__(self, app: FastAPI, service: FakeService) -> None:
        self.app = app
        self.service = service
        self.client = TestClient(app, base_url="http://testserver")

    def csrf(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str = "admin") -> dict[str, str]:
        headers = self.csrf()
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": username, "password": "heracles"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        return self.csrf()

    def token(self, **body: Any) -> str:
        """A token of the signed-in admin (its own client, so no cookie leaks into requests)."""
        owner = TestClient(self.app, base_url="http://testserver")
        headers = {"X-CSRF-Token": owner.get("/api/v2/auth/csrf").json()["token"]}
        r = owner.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "admin", "password": "heracles"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        headers = {"X-CSRF-Token": owner.get("/api/v2/auth/csrf").json()["token"]}
        payload: dict[str, Any] = {"name": "scim", "scope": "write", "expires_in_days": 30}
        payload.update(body)
        r = owner.post("/api/v2/auth/tokens", json=payload, headers=headers)
        assert r.status_code == 201, r.text
        return str(r.json()["secret"])

    def request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        content_type: str = SCIM,
    ) -> Any:
        sent = {"Authorization": f"Bearer {token}", **(headers or {})}
        if body is not None:
            content = json.dumps(body).encode()
        if content is not None:
            sent["Content-Type"] = content_type
        return self.client.request(method, f"/scim/v2{path}", content=content, headers=sent)


@pytest.fixture
def h(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    app = build_demo_app()
    service = FakeService()
    app.dependency_overrides[scim_router.get_scim_service] = lambda: service
    with TestClient(app):
        yield Harness(app, service)


@pytest.fixture
def tok(h: Harness) -> str:
    return h.token()


def _is_error(r: Any, status: int, scim_type: str | None = None) -> dict[str, Any]:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith(SCIM)
    body = r.json()
    assert body["schemas"] == [ERROR_SCHEMA]
    assert body["status"] == str(status)
    assert isinstance(body["detail"], str)
    if scim_type is not None:
        assert body["scimType"] == scim_type
    return cast("dict[str, Any]", body)


# -- authentication -------------------------------------------------------------------------------
def test_no_credentials_is_a_scim_401(h: Harness) -> None:
    r = h.client.get("/scim/v2/Users")
    _is_error(r, 401)
    assert r.headers["www-authenticate"].startswith("Bearer")


def test_a_session_cookie_never_works(h: Harness) -> None:
    csrf = h.login()
    assert h.client.get("/api/v2/auth/me").status_code == 200
    _is_error(h.client.get("/scim/v2/Users"), 401)
    _is_error(h.client.get("/scim/v2/Users", headers={"Session-Token": "x"}), 401)
    _is_error(h.client.post("/scim/v2/Users", json={"userName": "x"}, headers=csrf), 401)


def test_a_foreign_bearer_value_is_a_401(h: Harness) -> None:
    for value in ("Bearer abcdef", "Basic YWRtaW46aGVyYWNsZXM="):
        r = h.client.get("/scim/v2/Users", headers={"Authorization": value})
        _is_error(r, 401)
        assert r.headers["www-authenticate"].startswith("Bearer")


def test_an_invalid_token_is_a_401(h: Harness) -> None:
    r = h.client.get("/scim/v2/Users", headers={"Authorization": "Bearer hrc_nope.nope"})
    _is_error(r, 401)
    assert "invalid_token" in r.headers["www-authenticate"]


def test_a_read_token_reads_but_cannot_write(h: Harness) -> None:
    token = h.token(scope="read")
    assert h.request("GET", "/Users", token).status_code == 200
    r = h.request("POST", "/Users", token, body={"userName": "x"})
    _is_error(r, 403)
    assert "token_scope" not in r.text or "scope" in r.json()["detail"]
    assert "insufficient_scope" in r.headers["www-authenticate"]
    _is_error(h.request("DELETE", "/Users/id-1", token), 403)
    # a search is a read
    body = {"schemas": [SEARCH_REQUEST]}
    assert h.request("POST", "/Users/.search", token, body=body).status_code == 200
    assert h.service.users.calls[-1][0] == "search"


def test_a_type_limited_token(h: Harness) -> None:
    token = h.token(types=["user"])
    assert h.request("GET", "/Users", token).status_code == 200
    _is_error(h.request("GET", "/Groups", token), 403)
    _is_error(h.request("POST", "/Groups/.search", token, body={"schemas": [SEARCH_REQUEST]}), 403)
    # type-free discovery documents stay reachable
    assert h.request("GET", "/ServiceProviderConfig", token).status_code == 200
    assert h.request("GET", "/Schemas", token).status_code == 200
    group_token = h.token(types=["group"])
    _is_error(h.request("GET", "/Users", group_token), 403)
    assert h.request("GET", "/Groups", group_token).status_code == 200


def test_disabled_endpoint_is_404_everywhere(h: Harness, tok: str) -> None:
    state = cast("AppState", h.app.state.heracles)
    state.settings.scim.enabled = False
    for method, path in (
        ("GET", "/Users"),
        ("POST", "/Users"),
        ("GET", "/Groups/id-1"),
        ("GET", "/Schemas"),
        ("GET", "/ServiceProviderConfig"),
        ("GET", "/nothing"),
    ):
        _is_error(h.request(method, path, tok, body={}), 404)
    _is_error(h.client.get("/scim/v2/Users"), 404)  # not even a 401


# -- content types and bodies ---------------------------------------------------------------------
def test_responses_are_scim_json(h: Harness, tok: str) -> None:
    h.service.users.add(userName="ada")
    r = h.request("GET", "/Users", tok)
    assert r.headers["content-type"].startswith(SCIM)
    assert h.request("GET", "/Users/id-1", tok).headers["content-type"].startswith(SCIM)


def test_both_content_types_are_accepted(h: Harness, tok: str) -> None:
    for media in (SCIM, "application/json", "application/scim+json; charset=utf-8"):
        r = h.request(
            "POST", "/Users", tok, body={"userName": f"u{len(media)}"}, content_type=media
        )
        assert r.status_code == 201, (media, r.text)
    r = h.request("POST", "/Users", tok, content=b"userName=x", content_type="text/plain")
    _is_error(r, 415)


def test_malformed_bodies_are_invalid_syntax(h: Harness, tok: str) -> None:
    for raw in (b"{not json", b"", b"[1, 2]", b'"text"'):
        r = h.request("POST", "/Users", tok, content=raw)
        _is_error(r, 400, "invalidSyntax")
    _is_error(h.request("PUT", "/Users/id-1", tok, content=b"{"), 400, "invalidSyntax")
    _is_error(h.request("PATCH", "/Users/id-1", tok, content=b"{"), 400, "invalidSyntax")
    assert h.service.users.calls == []


def test_unauthenticated_malformed_body_is_401_first(h: Harness) -> None:
    r = h.client.post("/scim/v2/Users", content=b"{", headers={"Content-Type": SCIM})
    _is_error(r, 401)


# -- users and groups -----------------------------------------------------------------------------
@pytest.mark.parametrize(("collection", "kind"), [("Users", "users"), ("Groups", "groups")])
def test_crud_cycle(h: Harness, tok: str, collection: str, kind: str) -> None:
    ops = getattr(h.service, kind)
    name_key = "userName" if kind == "users" else "displayName"

    r = h.request("POST", f"/{collection}", tok, body={name_key: "one"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert r.headers["location"] == created["meta"]["location"]
    assert r.headers["etag"] == created["meta"]["version"]
    rid = created["id"]

    r = h.request("GET", f"/{collection}/{rid}", tok)
    assert r.status_code == 200 and r.json() == created
    assert r.headers["etag"] == created["meta"]["version"]

    r = h.request("PUT", f"/{collection}/{rid}", tok, body={name_key: "two"})
    assert r.status_code == 200 and r.json()[name_key] == "two"
    assert r.headers["etag"] == r.json()["meta"]["version"]

    patch = {
        "schemas": [PATCH_OP],
        "Operations": [{"op": "Replace", "path": name_key, "value": "three"}],
    }
    r = h.request("PATCH", f"/{collection}/{rid}", tok, body=patch)
    assert r.status_code == 200 and r.json()[name_key] == "three"
    assert r.headers["etag"] == r.json()["meta"]["version"]
    patched = next(c for c in ops.calls if c[0] == "patch")[1]
    assert patched[0] == rid and patched[1] == [PatchOp("replace", name_key, "three")]

    r = h.request("DELETE", f"/{collection}/{rid}", tok)
    assert r.status_code == 204 and r.content == b""
    _is_error(h.request("GET", f"/{collection}/{rid}", tok), 404)
    _is_error(h.request("DELETE", f"/{collection}/{rid}", tok), 404)
    _is_error(h.request("PUT", f"/{collection}/{rid}", tok, body={name_key: "x"}), 404)


def test_service_errors_keep_their_status_and_type(h: Harness, tok: str) -> None:
    _is_error(h.request("POST", "/Users", tok, body={"userName": "taken"}), 409, "uniqueness")
    h.service.users.add(userName="ada")
    patch = {"schemas": [PATCH_OP], "Operations": [{"op": "replace", "path": "id", "value": "x"}]}
    _is_error(h.request("PATCH", "/Users/id-1", tok, body=patch), 400, "mutability")
    bad = {"schemas": ["nope"], "Operations": []}
    _is_error(h.request("PATCH", "/Users/id-1", tok, body=bad), 400, "invalidSyntax")


def test_unexpected_errors_are_scim_500(h: Harness, tok: str) -> None:
    def boom(_: str) -> dict[str, Any]:
        raise RuntimeError("secret internals")

    h.service.users.get = boom  # type: ignore[method-assign]
    body = _is_error(h.request("GET", "/Users/id-1", tok), 500)
    assert "secret" not in body["detail"]


def test_directory_errors_are_scim_errors(h: Harness, tok: str) -> None:
    from heracles.ldap.client import DirectoryError, DirectoryUnavailableError

    def broken(_: str) -> dict[str, Any]:
        raise DirectoryError("ldap said no")

    def down(_: str) -> dict[str, Any]:
        raise DirectoryUnavailableError("gone")

    h.service.users.get = broken  # type: ignore[method-assign]
    _is_error(h.request("GET", "/Users/x", tok), 502)
    h.service.users.get = down  # type: ignore[method-assign]
    r = h.request("GET", "/Users/x", tok)
    _is_error(r, 503)
    assert r.headers["retry-after"]


# -- listing --------------------------------------------------------------------------------------
def _fill(h: Harness, n: int) -> None:
    for i in range(n):
        h.service.users.add(userName=f"user{i}")


def test_list_response_shape(h: Harness, tok: str) -> None:
    _fill(h, 3)
    body = h.request("GET", "/Users", tok).json()
    assert body["schemas"] == [LIST_RESPONSE]
    assert body["totalResults"] == 3 and body["startIndex"] == 1 and body["itemsPerPage"] == 3
    assert [r["userName"] for r in body["Resources"]] == ["user0", "user1", "user2"]


def test_empty_list(h: Harness, tok: str) -> None:
    body = h.request("GET", "/Groups", tok).json()
    assert body["totalResults"] == 0 and body["Resources"] == [] and body["itemsPerPage"] == 0


def test_pagination_parameters(h: Harness, tok: str) -> None:
    _fill(h, 5)
    state = cast("AppState", h.app.state.heracles)
    state.settings.scim.max_results = 4
    ops = h.service.users

    def last() -> tuple[Any, ...]:
        return cast("tuple[Any, ...]", ops.calls[-1][1])

    body = h.request("GET", "/Users?startIndex=2&count=2", tok).json()
    assert body["startIndex"] == 2 and body["itemsPerPage"] == 2
    assert [r["userName"] for r in body["Resources"]] == ["user1", "user2"]
    assert last()[1:3] == (2, 2)

    h.request("GET", "/Users", tok)
    assert last()[1:3] == (1, 4)  # default = the cap
    h.request("GET", "/Users?count=100", tok)
    assert last()[2] == 4  # capped
    h.request("GET", "/Users?startIndex=0", tok)
    assert last()[1] == 1
    h.request("GET", "/Users?startIndex=-7", tok)
    assert last()[1] == 1
    body = h.request("GET", "/Users?count=-3", tok).json()
    assert last()[2] == 0 and body["totalResults"] == 5 and body["itemsPerPage"] == 0
    _is_error(h.request("GET", "/Users?count=abc", tok), 400)


def test_sorting_parameters(h: Harness, tok: str) -> None:
    _fill(h, 2)
    ops = h.service.users
    h.request("GET", "/Users?sortBy=userName", tok)
    assert ops.calls[-1][1][3:] == ("userName", False)
    h.request("GET", "/Users?sortBy=userName&sortOrder=Descending", tok)
    assert ops.calls[-1][1][3:] == ("userName", True)
    h.request("GET", "/Users?sortOrder=ascending", tok)
    assert ops.calls[-1][1][3:] == (None, False)
    _is_error(h.request("GET", "/Users?sortOrder=sideways", tok), 400, "invalidValue")


def test_filter_is_parsed_and_passed(h: Harness, tok: str) -> None:
    _fill(h, 1)
    r = h.request("GET", '/Users?filter=userName eq "user0"', tok)
    assert r.status_code == 200
    assert h.service.users.calls[-1][1][0] == Compare("userName", "eq", "user0")
    h.request("GET", "/Users?filter=", tok)
    assert h.service.users.calls[-1][1][0] is None


def test_filter_errors_are_scim_errors(
    h: Harness, tok: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_: str) -> Filter:
        raise ScimError(400, "Bad filter", "invalidFilter")

    monkeypatch.setattr(scim_filter, "parse", refuse)
    _is_error(h.request("GET", "/Users?filter=(", tok), 400, "invalidFilter")
    body = {"schemas": [SEARCH_REQUEST], "filter": "("}
    _is_error(h.request("POST", "/Users/.search", tok, body=body), 400, "invalidFilter")


def test_attributes_and_excluded_attributes(h: Harness, tok: str) -> None:
    h.service.users.add(userName="ada", displayName="Ada", active=True)
    body = h.request("GET", "/Users?attributes=userName", tok).json()
    assert set(body["Resources"][0]) == {"userName", "id", "schemas"}
    body = h.request("GET", "/Users?excludedAttributes=displayName,active,meta", tok).json()
    assert set(body["Resources"][0]) == {"schemas", "id", "userName"}
    one = h.request("GET", "/Users/id-1?attributes=displayName", tok).json()
    assert set(one) == {"displayName", "id", "schemas"}
    one = h.request("GET", "/Users/id-1?excludedAttributes=active", tok).json()
    assert "active" not in one and "userName" in one
    r = h.request("POST", "/Users?attributes=userName", tok, body={"userName": "bob", "x": 1})
    assert r.status_code == 201 and "x" not in r.json()
    assert r.headers["etag"]  # the version of the full resource
    _is_error(
        h.request("GET", "/Users?attributes=a&excludedAttributes=b", tok), 400, "invalidSyntax"
    )


def test_search_endpoint(h: Harness, tok: str) -> None:
    _fill(h, 5)
    body = {
        "schemas": [SEARCH_REQUEST],
        "filter": 'userName eq "user1"',
        "startIndex": 2,
        "count": 2,
        "sortBy": "userName",
        "sortOrder": "descending",
        "attributes": ["userName"],
    }
    r = h.request("POST", "/Users/.search", tok, body=body)
    assert r.status_code == 200 and r.headers["content-type"].startswith(SCIM)
    out = r.json()
    assert out["schemas"] == [LIST_RESPONSE] and out["totalResults"] == 5
    assert out["startIndex"] == 2 and out["itemsPerPage"] == 2
    assert all(set(x) == {"userName", "id", "schemas"} for x in out["Resources"])
    flt, start, count, sort_by, desc = h.service.users.calls[-1][1]
    assert (flt, start, count, sort_by, desc) == (
        Compare("userName", "eq", "user1"),
        2,
        2,
        "userName",
        True,
    )


def test_search_request_is_validated(h: Harness, tok: str) -> None:
    _is_error(h.request("POST", "/Users/.search", tok, body={}), 400, "invalidSyntax")
    for extra in ({"count": "many"}, {"startIndex": True}, {"attributes": [1]}, {"filter": 3}):
        body = {"schemas": [SEARCH_REQUEST], **extra}
        _is_error(h.request("POST", "/Groups/.search", tok, body=body), 400, "invalidValue")
    both = {"schemas": [SEARCH_REQUEST], "attributes": ["a"], "excludedAttributes": ["b"]}
    _is_error(h.request("POST", "/Users/.search", tok, body=both), 400, "invalidSyntax")


# -- ETags ----------------------------------------------------------------------------------------
def test_if_none_match_on_get(h: Harness, tok: str) -> None:
    resource = h.service.users.add(userName="ada")
    version = resource["meta"]["version"]
    r = h.request("GET", "/Users/id-1", tok, headers={"If-None-Match": version})
    assert r.status_code == 304 and r.content == b"" and r.headers["etag"] == version
    r = h.request("GET", "/Users/id-1", tok, headers={"If-None-Match": f'"x", {version}'})
    assert r.status_code == 304
    assert h.request("GET", "/Users/id-1", tok, headers={"If-None-Match": "*"}).status_code == 304
    r = h.request("GET", "/Users/id-1", tok, headers={"If-None-Match": 'W/"stale"'})
    assert r.status_code == 200


def test_if_match_on_writes(h: Harness, tok: str) -> None:
    resource = h.service.users.add(userName="ada")
    version = resource["meta"]["version"]
    stale = {"If-Match": 'W/"stale"'}
    patch = {"schemas": [PATCH_OP], "Operations": [{"op": "add", "path": "title", "value": "x"}]}
    for method, body in (("PUT", {"userName": "b"}), ("PATCH", patch), ("DELETE", None)):
        r = h.request(method, "/Users/id-1", tok, body=body, headers=stale)
        _is_error(r, 412)
    assert not any(c[0] in ("replace", "patch", "delete") for c in h.service.users.calls)

    r = h.request("PUT", "/Users/id-1", tok, body={"userName": "b"}, headers={"If-Match": version})
    assert r.status_code == 200
    version = r.headers["etag"]
    r = h.request("PATCH", "/Users/id-1", tok, body=patch, headers={"If-Match": version})
    assert r.status_code == 200
    r = h.request("DELETE", "/Users/id-1", tok, headers={"If-Match": "*"})
    assert r.status_code == 204
    # If-Match on a resource that does not exist is a 404, not a 412
    _is_error(h.request("DELETE", "/Users/id-1", tok, headers={"If-Match": version}), 404)


# -- discovery ------------------------------------------------------------------------------------
def test_service_provider_config(h: Harness, tok: str) -> None:
    r = h.request("GET", "/ServiceProviderConfig", tok)
    assert r.status_code == 200 and r.headers["content-type"].startswith(SCIM)
    doc = r.json()
    assert doc["schemas"] == ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"]
    assert doc["patch"] == {"supported": True}
    assert doc["bulk"]["supported"] is False
    state = cast("AppState", h.app.state.heracles)
    assert doc["filter"] == {"supported": True, "maxResults": state.settings.scim.max_results}
    assert doc["changePassword"] == {"supported": True}
    assert doc["sort"] == {"supported": True} and doc["etag"] == {"supported": True}
    (scheme,) = doc["authenticationSchemes"]
    assert scheme["type"] == "oauthbearertoken" and scheme["primary"] is True
    assert scheme["name"] and scheme["description"]
    assert doc["meta"] == {
        "resourceType": "ServiceProviderConfig",
        "location": f"{BASE}/ServiceProviderConfig",
    }


def test_resource_types(h: Harness, tok: str) -> None:
    body = h.request("GET", "/ResourceTypes", tok).json()
    assert body["schemas"] == [LIST_RESPONSE] and body["totalResults"] == 2
    by_id = {r["id"]: r for r in body["Resources"]}
    assert set(by_id) == {"User", "Group"}
    user = by_id["User"]
    assert user["endpoint"] == "/Users" and user["schema"] == USER_SCHEMA
    assert user["schemaExtensions"] == [{"schema": ENTERPRISE_USER_SCHEMA, "required": False}]
    assert by_id["Group"]["endpoint"] == "/Groups" and "schemaExtensions" not in by_id["Group"]
    assert user["meta"]["location"] == f"{BASE}/ResourceTypes/User"
    one = h.request("GET", "/ResourceTypes/Group", tok)
    assert one.status_code == 200 and one.json() == by_id["Group"]
    _is_error(h.request("GET", "/ResourceTypes/Device", tok), 404)


def test_schemas(h: Harness, tok: str) -> None:
    body = h.request("GET", "/Schemas", tok).json()
    assert body["totalResults"] == 3
    by_id = {s["id"]: s for s in body["Resources"]}
    assert set(by_id) == {USER_SCHEMA, GROUP_SCHEMA, ENTERPRISE_USER_SCHEMA}
    for urn, doc in by_id.items():
        assert doc["schemas"] == [SCHEMA_SCHEMA]
        assert doc["meta"] == {"resourceType": "Schema", "location": f"{BASE}/Schemas/{urn}"}
        assert doc["attributes"]
    user = {a["name"]: a for a in by_id[USER_SCHEMA]["attributes"]}
    assert "externalId" not in user
    assert user["userName"]["required"] and user["userName"]["uniqueness"] == "server"
    assert user["password"]["mutability"] == "writeOnly" and user["password"]["returned"] == "never"
    assert user["groups"]["mutability"] == "readOnly" and user["groups"]["multiValued"]
    assert user["emails"]["multiValued"] and user["name"]["type"] == "complex"
    assert {s["name"] for s in user["name"]["subAttributes"]} == {
        "formatted",
        "familyName",
        "givenName",
    }
    group = {a["name"]: a for a in by_id[GROUP_SCHEMA]["attributes"]}
    assert group["displayName"]["required"] and group["members"]["multiValued"]
    one = h.request("GET", f"/Schemas/{GROUP_SCHEMA}", tok)
    assert one.status_code == 200 and one.json() == by_id[GROUP_SCHEMA]
    _is_error(h.request("GET", "/Schemas/urn:nope", tok), 404)


def test_discovery_needs_a_token(h: Harness) -> None:
    for path in ("/ServiceProviderConfig", "/ResourceTypes", "/Schemas", "/ResourceTypes/User"):
        _is_error(h.client.get(f"/scim/v2{path}"), 401)


# -- unknown routes -------------------------------------------------------------------------------
def test_unknown_routes_are_scim_404(h: Harness, tok: str) -> None:
    for method, path in (
        ("GET", "/Devices"),
        ("POST", "/Bulk"),
        ("GET", "/Users/a/b/c"),
        ("GET", ""),
    ):
        _is_error(h.request(method, path, tok, body={} if method == "POST" else None), 404)
    _is_error(h.client.get("/scim/v2/Devices"), 404)  # no token needed to learn it is not there


def test_validation_error_is_scim_400(h: Harness, tok: str) -> None:
    # a path parameter that cannot be missing, a query that cannot parse
    _is_error(h.request("GET", "/Users?startIndex=first", tok), 400, "invalidValue")


def test_scim_is_not_under_the_api_router(h: Harness, tok: str) -> None:
    # no CSRF header needed with a token, and the v2 error shape is not used
    r = h.request("POST", "/Users", tok, body={"userName": "x"})
    assert r.status_code == 201
    assert h.client.get("/api/v2/Users").status_code in (404, 401)
