"""API v1 on the demo application: one test per path plus an "existing client" scenario."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.domain import Domain
from heracles.api.state import AppState
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

BASE = demo.BASE
ZULU = f"uid=zzulu,ou=people,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
ADMINS = f"cn=admins,ou=groups,{BASE}"


def app_state(client: TestClient) -> AppState:
    return cast("FastAPI", client.app).state.heracles  # type: ignore[no-any-return]


def domain_of(client: TestClient) -> Domain:
    return cast("FastAPI", client.app).state.domain  # type: ignore[no-any-return]


def directory_of(client: TestClient) -> MemoryDirectory:
    return cast("MemoryDirectory", app_state(client).directories["main"])


class V1:
    """Thin v1 client keeping the session token."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.headers: dict[str, str] = {}

    def login(self, user: str = "admin", password: str = "heracles") -> V1:
        r = self.client.post(
            "/api/v1/login", json={"directory": "main", "user": user, "password": password}
        )
        assert r.status_code == 200, r.text
        self.headers = {"Session-Token": r.json()}
        return self

    def call(self, method: str, path: str, **kw: Any) -> Any:
        return self.client.request(method, f"/api/v1{path}", headers=self.headers, **kw)

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_demo_app()) as c:
        yield c


@pytest.fixture
def v1(client: TestClient) -> V1:
    return V1(client).login()


# -- authentication -----------------------------------------------------------------------------
def test_login_logout_token(client: TestClient) -> None:
    api = V1(client).login()
    token = api.headers["Session-Token"]
    assert api.get("/token").json() == token
    assert api.call("POST", "/logout").status_code == 204
    r = api.get("/token")
    assert r.status_code == 401 and "message" in r.json()


def test_login_accepts_legacy_spellings(client: TestClient) -> None:
    r = client.post("/api/v1/login", json={"username": "admin", "password": "heracles"})
    assert r.status_code == 200
    token = r.json()
    assert client.get("/api/v1/token", headers={"X-Session-Token": token}).json() == token


def test_login_failures(client: TestClient) -> None:
    bad = client.post("/api/v1/login", json={"user": "admin", "password": "nope"})
    assert bad.status_code == 401 and "message" in bad.json()
    unknown = client.post(
        "/api/v1/login", json={"directory": "zzz", "user": "admin", "password": "heracles"}
    )
    assert unknown.status_code == 422
    missing = client.post("/api/v1/login", json={"password": "x"})
    assert missing.status_code == 422


def test_directories(client: TestClient) -> None:
    r = client.get("/api/v1/directories")
    assert r.status_code == 200
    assert r.json() == {"main": "Demo directory"}


def test_second_factor_accounts_are_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = app_state(client)
    monkeypatch.setattr(state.second_factor, "methods_for", lambda _dn: ["totp"]  # pyright: ignore[reportUnknownLambdaType])
    r = client.post("/api/v1/login", json={"user": "admin", "password": "heracles"})
    assert r.status_code == 401
    assert "Second factor" in r.json()["message"]


def test_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/types").status_code == 401
    assert client.get("/api/v1/types", headers={"Session-Token": "bogus"}).status_code == 401


def test_v1_is_csrf_exempt(client: TestClient) -> None:
    api = V1(client).login()
    r = api.call("POST", "/objects/USER", json={"attrs": {"user": {"sn": "A", "givenName": "B"}}})
    assert r.status_code != 403


# -- types --------------------------------------------------------------------------------------
def test_types(v1: V1) -> None:
    listed = v1.get("/types").json()
    assert listed["USER"] == "User" and listed["OGROUP"] == "Group"
    info = v1.get("/types/USER").json()
    assert info["mainAttr"] == "uid" and info["mainTab"] == "user"
    assert {"class": "posixAccount", "name": "Unix"} in info["tabs"]
    assert v1.get("/types/user").status_code == 200  # Heracles name accepted too
    assert v1.get("/types/NOPE").status_code == 404
    tab = v1.get("/types/USER/user").json()
    assert tab["sections_order"] == list(tab["sections"])
    assert "sn" in tab["sections"]["identity"]["attrs"]
    assert v1.get("/types/USER/nope").status_code == 404


# -- search -------------------------------------------------------------------------------------
def test_search_variants(v1: V1) -> None:
    names = v1.get("/objects/USER").json()
    assert names[ASMITH] == "Alice Smith"
    r = v1.get("/objects/USER", params={"attrs[uid]": "1", "attrs[mail]": "*"}).json()
    assert r[ASMITH] == {"uid": "asmith", "mail": ["asmith@heracles.test"]}
    b64 = v1.get("/objects/USER", params={"attrs[uid]": "b64"}).json()
    assert b64[ASMITH] == {"uid": ["YXNtaXRo"]}
    raw = v1.get("/objects/USER", params={"attrs[uid]": "raw"}).json()
    assert raw[ASMITH] == {"uid": ["asmith"]}
    filtered = v1.get("/objects/USER", params={"filter": "(uid=as*)"}).json()
    assert list(filtered) == [ASMITH]
    paris = f"ou=paris,{BASE}"
    scoped = v1.get("/objects/USER", params={"base": paris, "scope": "subtree"}).json()
    assert ASMITH in scoped and ZULU not in scoped
    one = v1.get("/objects/USER", params={"base": paris, "scope": "one"}).json()
    assert one == {}
    assert v1.get("/objects/USER", params={"filter": "(uid="}).status_code == 400
    assert v1.get("/objects/NOPE").status_code == 404


def test_search_hides_unreadable_entries_and_attributes(client: TestClient) -> None:
    api = V1(client).login("bmartin")
    found = api.get("/objects/USER", params={"attrs[uid]": "1", "attrs[userPassword]": "1"}).json()
    for row in found.values():
        assert "userPassword" not in row


def _install_templates(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    @dataclass
    class Info:
        dn: str
        name: str
        type_name: str

    def list_templates(ctx: object, type_name: str) -> list[Info]:
        calls["list"] = type_name
        return [Info("cn=tpl,ou=templates," + BASE, "tpl", type_name)]

    def template_fields(ctx: object, type_name: str, template_dn: str) -> dict[str, list[str]]:
        calls["fields"] = template_dn
        return {"main": ["sn", "givenName"]}

    def apply_template(
        ctx: object, type_name: str, template_dn: str, values: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        calls["apply"] = (template_dn, values)
        main = {**values.get("main", {}), "uid": "fromtpl"}
        return {"main": main}

    module = types.ModuleType("heracles.objects.templates")
    module.list_templates = list_templates  # type: ignore[attr-defined]
    module.template_fields = template_fields  # type: ignore[attr-defined]
    module.apply_template = apply_template  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "heracles.objects.templates", module)
    return calls


def test_templates_search_fields_and_create(v1: V1, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_templates(monkeypatch)
    found = v1.get("/objects/USER", params={"templates": "true"}).json()
    assert found == {"cn=tpl,ou=templates," + BASE: "tpl"}
    tpl = "cn=tpl,ou=templates," + BASE
    fields = v1.get(f"/objects/USER/{tpl}/templatefields").json()
    assert fields == {"user": ["sn", "givenName"]}
    assert calls["fields"] == tpl
    r = v1.call(
        "POST",
        "/objects/USER",
        json={"attrs": {"user": {"sn": "Tpl", "givenName": "Una"}}, "template": tpl},
    )
    assert r.status_code == 201, r.text
    assert r.json() == f"uid=fromtpl,ou=people,{BASE}"
    assert calls["apply"][0] == tpl


def test_templates_unavailable_before_merge(v1: V1, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "heracles.objects.templates", None)
    assert v1.get("/objects/USER", params={"templates": "true"}).status_code == 501


# -- objects, tabs, attributes ------------------------------------------------------------------
def test_create_and_read(v1: V1) -> None:
    r = v1.call(
        "POST",
        "/objects/USER",
        json={
            "attrs": {
                "user": {"givenName": "Zed", "sn": "Zulu", "uid": "zzulu", "mail": ["z@x.org"]},
                "personalInfo": {"personalTitle": "Dr"},
            }
        },
    )
    assert r.status_code == 201, r.text
    assert r.json() == ZULU
    tabs = v1.get(f"/objects/USER/{ZULU}").json()
    by_class = {t["class"]: t for t in tabs}
    assert by_class["user"]["active"] is True
    assert by_class["personalInfo"]["active"] is True
    assert by_class["posixAccount"]["active"] is False
    values = v1.get(f"/objects/USER/{ZULU}/user").json()
    assert values["sn"] == "Zulu" and values["mail"] == "z@x.org"
    assert v1.get(f"/objects/USER/{ZULU}/user/uid").json() == "zzulu"
    assert v1.get(f"/objects/USER/{ZULU}/posixAccount").status_code == 404


def test_create_errors(v1: V1) -> None:
    r = v1.call("POST", "/objects/USER", json={"attrs": {"user": {"sn": "Only"}}})
    assert r.status_code == 422 and r.json()["fields"]
    r = v1.call("POST", "/objects/USER", json={"attrs": {"nope": {"a": 1}}})
    assert r.status_code == 422 and "nope" in r.json()["fields"]
    r = v1.call("POST", "/objects/USER", json={"attrs": {"user": {"bogus": 1}}})
    assert r.status_code == 422 and "user.bogus" in r.json()["fields"]
    assert v1.call("POST", "/objects/USER", json={"attrs": []}).status_code == 400
    assert v1.call("POST", "/objects/USER", json={}).status_code == 400


def test_patch_object_tab_attribute(v1: V1) -> None:
    patch = v1.call("PATCH", f"/objects/USER/{ASMITH}", json={"user": {"description": "obj"}})
    assert patch.status_code == 200 and patch.json() == ASMITH
    assert v1.get(f"/objects/USER/{ASMITH}/user/description").json() == "obj"
    assert v1.call("PATCH", f"/objects/USER/{ASMITH}/user", json={"description": "tab"}).json()
    assert v1.get(f"/objects/USER/{ASMITH}/user/description").json() == "tab"
    put = v1.call("PUT", f"/objects/USER/{ASMITH}/user/description", json="attr")
    assert put.status_code == 200 and put.json() == ASMITH
    assert v1.get(f"/objects/USER/{ASMITH}/user/description").json() == "attr"
    reset = v1.call("DELETE", f"/objects/USER/{ASMITH}/user/description")
    assert reset.status_code == 200 and reset.json() == ""
    bad = v1.call("PATCH", f"/objects/USER/{ASMITH}/user", json={"nope": "x"})
    assert bad.status_code == 422
    assert v1.get(f"/objects/USER/{ASMITH}/user/nope").status_code == 404


def test_multivalued_values(v1: V1) -> None:
    url = f"/objects/OGROUP/{ADMINS}/ogroup/member"
    before = v1.get(url).json()
    assert isinstance(before, list)
    added = v1.call("PATCH", f"{url}/values", json=[ASMITH])
    assert added.status_code == 200 and added.json() == ADMINS
    assert ASMITH in v1.get(url).json()
    # adding again is idempotent
    v1.call("PATCH", f"{url}/values", json=[ASMITH])
    assert v1.get(url).json().count(ASMITH) == 1
    removed = v1.call("DELETE", f"{url}/values", json=[ASMITH])
    assert removed.status_code == 204
    assert ASMITH not in v1.get(url).json()
    single = f"/objects/USER/{ASMITH}/user/uid/values"
    assert v1.call("PATCH", single, json=["x"]).status_code == 400


def test_disable_tab(v1: V1) -> None:
    assert (
        v1.call(
            "PATCH", f"/objects/USER/{ASMITH}", json={"personalInfo": {"personalTitle": "Dr"}}
        ).status_code
        == 200
    )
    assert v1.get(f"/objects/USER/{ASMITH}/personalInfo").status_code == 200
    assert v1.call("DELETE", f"/objects/USER/{ASMITH}/personalInfo").status_code == 204
    tabs = {t["class"]: t["active"] for t in v1.get(f"/objects/USER/{ASMITH}").json()}
    assert tabs["personalInfo"] is False


def test_delete_object(v1: V1) -> None:
    assert v1.call("DELETE", f"/objects/USER/{ASMITH}").status_code == 204
    assert v1.get(f"/objects/USER/{ASMITH}").status_code == 404
    assert v1.call("DELETE", f"/objects/USER/{ASMITH}").status_code == 404


def test_acl_is_enforced(client: TestClient) -> None:
    api = V1(client).login("bmartin")
    assert api.call("DELETE", f"/objects/USER/{ASMITH}").status_code == 403
    r = api.call("PATCH", f"/objects/USER/{ASMITH}", json={"user": {"description": "x"}})
    assert r.status_code == 403
    r = api.call("POST", "/objects/USER", json={"attrs": {"user": {"sn": "A", "givenName": "B"}}})
    assert r.status_code == 403


def test_edit_lock_held_by_someone_else(client: TestClient, v1: V1) -> None:
    other = V1(client).login("helpdesk")
    helpdesk_dn = f"uid=helpdesk,ou=people,{BASE}"
    domain_of(client).locks("main", directory_of(client)).acquire(ASMITH, helpdesk_dn)
    r = v1.call("PATCH", f"/objects/USER/{ASMITH}", json={"user": {"description": "x"}})
    assert r.status_code == 409
    assert other.get(f"/objects/USER/{ASMITH}").status_code == 200


# -- user lock / archive / recovery -------------------------------------------------------------
def test_userlock(v1: V1) -> None:
    assert v1.get(f"/userlock/{ASMITH}").json() is False
    assert v1.call("PUT", f"/userlock/{ASMITH}", json=True).status_code == 204
    assert v1.get(f"/userlock/{ASMITH}").json() is True
    assert v1.call("PUT", f"/userlock/{ASMITH}", json=False).status_code == 204
    assert v1.get(f"/userlock/{ASMITH}").json() is False
    assert v1.get(f"/userlock/uid=ghost,{BASE}").status_code == 404


def test_userlock_requires_rights(client: TestClient) -> None:
    api = V1(client).login("bmartin")
    assert api.call("PUT", f"/userlock/{ASMITH}", json=True).status_code == 403


def test_archive(v1: V1, client: TestClient) -> None:
    assert v1.call("POST", f"/archive/USER/{ASMITH}").status_code == 204
    assert v1.get(f"/objects/USER/{ASMITH}").status_code == 404
    directory = directory_of(client)
    archived = list(directory.search(f"ou=archive,{BASE}", "(objectClass=*)"))
    assert any(e.text("fdArchivedOriginDn") == ASMITH for e in archived)


def test_archive_errors(client: TestClient, v1: V1) -> None:
    assert v1.call("POST", f"/archive/USER/uid=ghost,{BASE}").status_code == 404
    assert V1(client).login("bmartin").call("POST", f"/archive/USER/{ASMITH}").status_code == 403


def test_recovery(client: TestClient, v1: V1) -> None:
    r = v1.get("/recovery", params={"email": "asmith@heracles.test"})
    assert r.status_code == 200
    body = r.json()
    assert body["login"] == "asmith" and body["token"]
    payload = {
        "token": body["token"],
        "login": "asmith",
        "password1": "N3w-passw0rd!x",
        "password2": "N3w-passw0rd!x",
    }
    mismatch = v1.call("PUT", "/recovery", json={**payload, "password2": "other"})
    assert mismatch.status_code == 400
    assert v1.call("PUT", "/recovery", json=payload).status_code == 204
    again = v1.call("PUT", "/recovery", json=payload)
    assert again.status_code == 400 and "message" in again.json()
    directory = directory_of(client)
    entry = directory.get(ASMITH, ["userPassword"])
    assert entry is not None
    stored = entry.text("userPassword")
    assert stored and stored.startswith("{")
    assert v1.get("/recovery", params={"email": "nobody@x.org"}).status_code == 404
    assert v1.get("/recovery").status_code == 400


# -- the OpenAPI contract -----------------------------------------------------------------------
CONTRACT = [
    ("post", "/login"),
    ("get", "/directories"),
    ("post", "/logout"),
    ("get", "/token"),
    ("get", "/types"),
    ("get", "/types/{type}"),
    ("get", "/types/{type}/{tab}"),
    ("get", "/objects/{type}"),
    ("post", "/objects/{type}"),
    ("get", "/objects/{type}/{dn}"),
    ("delete", "/objects/{type}/{dn}"),
    ("patch", "/objects/{type}/{dn}"),
    ("get", "/objects/{type}/{dn}/templatefields"),
    ("get", "/objects/{type}/{dn}/{tab}"),
    ("patch", "/objects/{type}/{dn}/{tab}"),
    ("delete", "/objects/{type}/{dn}/{tab}"),
    ("get", "/objects/{type}/{dn}/{tab}/{attribute}"),
    ("put", "/objects/{type}/{dn}/{tab}/{attribute}"),
    ("delete", "/objects/{type}/{dn}/{tab}/{attribute}"),
    ("patch", "/objects/{type}/{dn}/{tab}/{attribute}/values"),
    ("delete", "/objects/{type}/{dn}/{tab}/{attribute}/values"),
    ("get", "/userlock/{dn}"),
    ("put", "/userlock/{dn}"),
    ("post", "/archive/{type}/{dn}"),
    ("get", "/recovery"),
    ("put", "/recovery"),
]


def test_openapi_covers_the_contract(client: TestClient) -> None:
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    doc = r.json()
    assert doc["servers"] == [{"url": "/api/v1"}]
    assert doc["components"]["securitySchemes"]["session"]["name"] == "Session-Token"
    for method, path in CONTRACT:
        assert method in doc["paths"].get(path, {}), f"{method.upper()} {path} missing"
    assert doc["paths"]["/login"]["post"]["security"] == []


# -- scripted existing-client scenario ----------------------------------------------------------
def test_existing_client_scenario(client: TestClient) -> None:
    c = client
    token = c.post(
        "/api/v1/login", json={"directory": "main", "user": "admin", "password": "heracles"}
    ).json()
    h = {"Session-Token": token}
    found = c.get(
        "/api/v1/objects/USER", params={"attrs[uid]": "1", "filter": "(uid=a*)"}, headers=h
    )
    assert found.status_code == 200 and ASMITH in found.json()
    created = c.post(
        "/api/v1/objects/USER",
        headers=h,
        json={
            "attrs": {
                "user": {"givenName": "Zed", "sn": "Zulu", "uid": "zzulu"},
                "personalInfo": {"personalTitle": "Dr"},
            }
        },
    )
    assert created.status_code == 201
    dn = created.json()
    patched = c.patch(f"/api/v1/objects/USER/{dn}/user", headers=h, json={"description": "d"})
    assert patched.status_code == 200
    assert (
        c.put(f"/api/v1/objects/USER/{dn}/user/description", headers=h, json="hello").json() == dn
    )
    assert c.get(f"/api/v1/objects/USER/{dn}/user/description", headers=h).json() == "hello"
    # add / remove values on a group
    url = f"/api/v1/objects/OGROUP/{ADMINS}/ogroup/member/values"
    assert c.patch(url, headers=h, json=[dn]).status_code == 200
    members = c.get(f"/api/v1/objects/OGROUP/{ADMINS}/ogroup/member", headers=h).json()
    assert dn in members
    assert c.request("DELETE", url, headers=h, json=[dn]).status_code == 204
    # lock, delete, logout
    assert c.put(f"/api/v1/userlock/{dn}", headers=h, json=True).status_code == 204
    assert c.get(f"/api/v1/userlock/{dn}", headers=h).json() is True
    assert c.delete(f"/api/v1/objects/USER/{dn}", headers=h).status_code == 204
    assert c.post("/api/v1/logout", headers=h).status_code == 204
    assert c.get("/api/v1/types", headers=h).status_code == 401
