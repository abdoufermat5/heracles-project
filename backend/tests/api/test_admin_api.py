"""``/api/v2/admin`` on the demo application."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.state import AppState
from heracles.demo import BASE
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"
HELPDESK_ROLE = f"cn=helpdesk,ou=aclroles,{BASE}"
ADMIN = f"uid=admin,ou=people,{BASE}"
BMARTIN = f"uid=bmartin,ou=people,{PARIS}"


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
        return self.client.get(f"/api/v2/admin{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2/admin{path}", json=body, headers=self.headers)

    def put(self, path: str, body: Any) -> Any:
        return self.client.put(f"/api/v2/admin{path}", json=body, headers=self.headers)

    def delete(self, path: str, **params: Any) -> Any:
        return self.client.delete(f"/api/v2/admin{path}", params=params, headers=self.headers)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_demo_app(), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def admin(client: TestClient) -> Api:
    return Api(client).login("admin")


def dnp(dn: str) -> str:
    return quote(dn, safe="")


def test_requires_login(client: TestClient) -> None:
    assert Api(client).get("/capabilities").status_code == 401


def test_capabilities(client: TestClient) -> None:
    caps = Api(client).login("admin").get("/capabilities").json()
    assert caps["is_admin"] is False  # the demo admin is not a bootstrap admin, only ACL admin
    assert caps["acl"] and caps["config"] and caps["config_write"]
    user = Api(TestClient(build_demo_app(), base_url="http://testserver")).login("bmartin")
    assert user.get("/capabilities").json() == {
        "is_admin": False,
        "acl": False,
        "config": False,
        "config_write": False,
        "hooks": False,
        "health": False,
        "plugins": False,
        "tasks": False,
    }
    assert user.get("/acl/roles").status_code == 403
    assert user.get("/config").status_code == 403
    assert user.get("/checks").status_code == 403


def test_helpdesk_cannot_manage(client: TestClient) -> None:
    api = Api(client).login("helpdesk")
    assert api.get("/acl/assignments").status_code == 403
    assert api.put(f"/acl/assignments/{dnp(BASE)}", {"assignments": []}).status_code == 403
    assert api.put("/config", {"changes": {"timezone": "UTC"}}).status_code == 403


def test_catalog(admin: Api) -> None:
    catalog = admin.get("/acl/catalog").json()
    categories = {c["category"]: c for c in catalog["categories"]}
    assert "user" in categories and "acl" in categories
    keys = {o["key"] for o in categories["user"]["objects"]}
    assert "user/user" in keys
    user = next(o for o in categories["user"]["objects"] if o["key"] == "user/user")
    assert any(a["name"] == "sn" for a in user["attributes"])
    assert categories["user"]["wildcard"] == "user/0"


def test_role_crud(admin: Api) -> None:
    roles = admin.get("/acl/roles").json()
    helpdesk = next(r for r in roles if r["cn"] == "helpdesk")
    assert helpdesk["used_by"] == 1
    assert helpdesk["templates"][0]["blocks"][0]["object"] == "user/user"

    created = admin.post(
        "/acl/roles",
        {
            "base": PARIS,
            "cn": "paris-readers",
            "description": "Read only",
            "templates": [
                {
                    "index": 0,
                    "blocks": [
                        {
                            "object": "user/user",
                            "rights": "r",
                            "attributes": [{"name": "mail", "rights": "rw"}],
                        }
                    ],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    dn = created.json()["dn"]
    assert dn == f"cn=paris-readers,ou=aclroles,{PARIS}"
    assert created.json()["templates"][0]["raw"] == "0:user/user;r#mail;rw"

    bad = admin.post(
        "/acl/roles", {"cn": "x", "templates": [{"blocks": [{"object": "a", "rights": "q"}]}]}
    )
    assert bad.status_code == 422
    assert "templates.0.blocks.0.rights" in bad.json()["error"]["fields"]

    updated = admin.put(f"/acl/roles/{dnp(dn)}", {"description": "Changed"})
    assert updated.json()["description"] == "Changed"
    assert admin.get(f"/acl/roles/{dnp(dn)}").json()["cn"] == "paris-readers"
    assert admin.delete(f"/acl/roles/{dnp(dn)}").status_code == 204
    assert admin.get(f"/acl/roles/{dnp(dn)}").status_code == 404

    in_use = admin.delete(f"/acl/roles/{dnp(HELPDESK_ROLE)}")
    assert in_use.status_code == 409


def test_assignments_roundtrip_and_effect(client: TestClient, admin: Api) -> None:
    items = admin.get(f"/acl/assignments/{dnp(BASE)}").json()["assignments"]
    assert [i["index"] for i in items] == [0, 1, 2]
    assert admin.put(f"/acl/assignments/{dnp(BASE)}", {"assignments": items}).status_code == 200
    everything = admin.get("/acl/assignments").json()
    assert {g["dn"] for g in everything} == {BASE, f"ou=lyon,{BASE}"}

    # give bmartin the helpdesk role on Paris, then check the effective rights
    new = {
        "index": 0,
        "scope": "subtree",
        "role": HELPDESK_ROLE,
        "members": [BMARTIN],
        "user_filter": None,
        "target_filter": None,
    }
    saved = admin.put(f"/acl/assignments/{dnp(PARIS)}", {"assignments": [new]})
    assert saved.status_code == 200, saved.text
    report = admin.post(
        "/acl/check",
        {
            "user": BMARTIN,
            "dn": f"uid=asmith,ou=people,{PARIS}",
            "object": "user/user",
            "attributes": ["userPassword", "sn"],
        },
    ).json()
    assert report["attributes"]["userPassword"] == "rw"
    assert report["attributes"]["sn"] == "r"
    assert report["bootstrap_admin"] is False

    invalid = admin.put(
        f"/acl/assignments/{dnp(PARIS)}", {"assignments": [{**new, "scope": "psub"}]}
    )
    assert invalid.status_code == 422
    assert admin.put(f"/acl/assignments/{dnp(PARIS)}", {"assignments": []}).status_code == 200
    assert admin.get(f"/acl/assignments/{dnp('ou=none,' + BASE)}").status_code == 404


def test_department_acl_tab(client: TestClient, admin: Api) -> None:
    descriptor = client.get("/api/v2/types/department").json()
    tab = next(t for t in descriptor["tabs"] if t["name"] == "acl")
    assert tab["optional"] is True
    detail = client.get(f"/api/v2/objects/department/{dnp(f'ou=lyon,{BASE}')}").json()
    assert detail["tabs"]["acl"]["active"] is True
    values = detail["tabs"]["acl"]["values"]["assignments"]
    assert values[0]["scope"] == "subtree"
    assert values[0]["members"][0].startswith("cn=lyon-managers")

    paris = f"/api/v2/objects/department/{dnp(PARIS)}"
    body = {
        "tabs": {
            "acl": {
                "active": True,
                "values": {
                    "assignments": [
                        {
                            "index": 0,
                            "scope": "base",
                            "role": HELPDESK_ROLE,
                            "members": ["*"],
                            "user_filter": None,
                            "target_filter": None,
                        }
                    ]
                },
            }
        }
    }
    patched = client.patch(paris, json=body, headers=admin.headers)
    assert patched.status_code == 200, patched.text
    stored = admin.get(f"/acl/assignments/{dnp(PARIS)}").json()["assignments"]
    assert stored[0]["scope"] == "base" and stored[0]["members"] == [
        {"dn": "*", "kind": "everyone"}
    ]


def test_config_get_and_put(client: TestClient, admin: Api) -> None:
    view = admin.get("/config").json()
    assert view["exists"] is False and view["can_write"] is True
    fields = {f["key"]: f for f in view["fields"]}
    assert fields["password_min_length"]["value"] == 8
    assert fields["password_min_length"]["source"] == "default"
    assert fields["password_min_length"]["honoured"] is True
    assert fields["recovery_salt"]["secret"] is True

    saved = admin.put(
        "/config", {"changes": {"password_min_length": 14, "login_attribute": "mail"}}
    )
    assert saved.status_code == 200, saved.text
    fields = {f["key"]: f for f in saved.json()["fields"]}
    assert fields["password_min_length"]["source"] == "directory"
    app = cast("FastAPI", client.app)
    state = cast("AppState", app.state.heracles)
    assert state.policy.min_length == 14  # applied without restart
    assert state.login_config.login_attribute == "mail"

    invalid = admin.put("/config", {"changes": {"password_min_length": "x", "bogus": 1}})
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]["fields"]) == {"password_min_length", "bogus"}
    reserved = admin.put("/config", {"changes": {"tab_hooks": []}})
    assert reserved.status_code == 422


def test_hooks_endpoint(admin: Api) -> None:
    view = admin.get("/hooks").json()
    assert view["hooks"] == [] and "posixAccount" in view["tabs"] and "check" in view["modes"]
    saved = admin.put(
        "/hooks",
        {
            "hooks": [
                {"tab": "user", "mode": "postcreate", "command": "echo %uid%", "enabled": True},
                {"tab": "posixAccount", "mode": "premodify", "command": "true", "enabled": False},
            ],
            "display_output": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["display_output"] is True
    assert saved.json()["hooks"][1]["enabled"] is False
    bad = admin.put("/hooks", {"hooks": [{"tab": "user", "mode": "nope", "command": ""}]})
    assert bad.status_code == 422
    assert set(bad.json()["error"]["fields"]) == {"hooks.0.mode", "hooks.0.command"}


def test_hook_runs_on_object_events(client: TestClient, admin: Api, tmp_path: Any) -> None:
    marker = tmp_path / "marker"
    admin.put(
        "/hooks",
        {"hooks": [{"tab": "user", "mode": "premodify", "command": f"echo no >{marker}; exit 1"}]},
    )
    r = client.patch(
        f"/api/v2/objects/user/{dnp(BMARTIN)}",
        json={"tabs": {"main": {"active": True, "values": {"sn": "Changed"}}}},
        headers=admin.headers,
    )
    assert r.status_code == 422, r.text
    assert marker.read_text().strip() == "no"
    after = client.get(f"/api/v2/objects/user/{dnp(BMARTIN)}").json()
    assert after["tabs"]["main"]["values"]["sn"] == "Martin"


def test_health_checks_and_fix(admin: Api) -> None:
    results = {r["id"]: r for r in admin.get("/checks").json()}
    assert results["default_roles"]["status"] == "warning"
    fixed = admin.post("/checks/default_roles/fix", {"dns": []})
    assert fixed.status_code == 200, fixed.text
    assert len(fixed.json()["result"]["fixed"]) == 3
    assert fixed.json()["check"]["status"] == "ok"
    assert admin.post("/checks/duplicate_ids/fix", {}).status_code == 404


def test_plugins_page(admin: Api) -> None:
    plugins = admin.get("/plugins").json()
    names = {p["name"] for p in plugins}
    assert {"acl_admin", "posix", "audit"} <= names
    own = next(p for p in plugins if p["name"] == "acl_admin")
    assert own["enabled"] is True
    assert any(t["name"] == "acl_role" for t in own["types"])
    assert any(t["type"] == "department" and t["name"] == "acl" for t in own["tabs"])


def test_tasks_dashboard(client: TestClient, admin: Api) -> None:
    empty = admin.get("/tasks").json()
    assert empty["summary"]["total"] == 0 and empty["kinds"]
    r = client.post(
        "/api/v2/objects/audit_task",
        json={
            "base": BASE,
            "tabs": {"main": {"active": True, "values": {"cn": "purge-audit"}}},
        },
        headers=admin.headers,
    )
    assert r.status_code == 201, r.text
    task_dn = r.json()["dn"]
    listed = admin.get("/tasks").json()
    assert listed["summary"]["total"] == 1
    row = listed["tasks"][0]
    assert row["kind"] == "audit_task" and row["status"] == "Activated" and row["can_run"] is True
    assert admin.get("/tasks", kind="other").json()["tasks"] == []
    assert admin.get("/tasks", status="Deactivated").json()["tasks"] == []

    queued = admin.post(f"/tasks/{dnp(task_dn)}/run")
    assert queued.status_code == 200 and queued.json()["queued"] is True
    assert admin.post(f"/tasks/{dnp('cn=none,' + BASE)}/run").status_code == 404
    retried = admin.post(f"/tasks/{dnp(task_dn)}/retry")
    assert retried.json()["retried"] == []
    helpdesk = Api(TestClient(build_demo_app(), base_url="http://testserver")).login("bmartin")
    assert helpdesk.post(f"/tasks/{dnp(task_dn)}/run").status_code in (403, 404)
