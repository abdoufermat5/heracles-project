"""``/api/v2/admin`` on the demo application."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.acl import serialise_assignment
from heracles.acl.admin import template_to_json
from heracles.acl.model import AclAssignment, AclScope
from heracles.api.settings import ApiSettings, PluginsSettings, TriggersSettings
from heracles.api.state import AppState
from heracles.demo import BASE
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.schema import names as schema
from heracles.server import build_demo_app, create_full_app

PARIS = f"ou=paris,{BASE}"
HELPDESK_ROLE = f"cn=helpdesk,ou=aclroles,{BASE}"
DELEGATE_ROLE = f"cn=dept-manager,ou=aclroles,{BASE}"
FULL_ADMIN_ROLE = f"cn=full-admin,ou=aclroles,{BASE}"
ADMIN = f"uid=admin,ou=people,{BASE}"
BMARTIN = f"uid=bmartin,ou=people,{PARIS}"


def _delegate(client: TestClient) -> None:
    """Give bmartin a role that manages assignments without holding every right."""
    state = cast("AppState", cast("FastAPI", client.app).state.heracles)
    directory = cast("MemoryDirectory", state.directories["main"])
    directory.add(
        DELEGATE_ROLE,
        {
            "objectClass": [schema.OC.ACL_ROLE.encode()],
            "cn": [b"dept-manager"],
            schema.ATTR.ACL_TEMPLATE: [
                b"0:user/user;rw,department/department;r,acl/aclAssignment;rw"
            ],
        },
    )
    value = serialise_assignment(
        AclAssignment(3, AclScope.SUBTREE, DELEGATE_ROLE, (BMARTIN,))
    ).encode()
    directory.modify(BASE, [Modification("add", schema.ATTR.ACL_ENTRY, [value])])


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
    assert caps["io"] is True  # the demo mounts the import/export plugin
    user = Api(TestClient(build_demo_app(), base_url="http://testserver")).login("bmartin")
    assert user.get("/capabilities").json() == {
        "is_admin": False,
        "console": False,
        "acl": False,
        "config": False,
        "config_write": False,
        "hooks": False,
        "health": False,
        "plugins": False,
        "tasks": False,
        "io": True,  # the demo exposes every plugin, import/export included
    }
    assert user.get("/acl/roles").status_code == 403
    assert user.get("/config").status_code == 403
    assert user.get("/checks").status_code == 403


def test_console_is_for_people_who_manage_others(client: TestClient) -> None:
    assert Api(client).login("admin").get("/capabilities").json()["console"] is True
    assert Api(client).login("helpdesk").get("/capabilities").json()["console"] is True


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


def test_assignment_cannot_grant_rights_the_caller_does_not_hold(client: TestClient) -> None:
    _delegate(client)
    api = Api(client).login("bmartin")
    escalation = {
        "assignments": [{"scope": "subtree", "role": FULL_ADMIN_ROLE, "members": [BMARTIN]}]
    }
    refused = api.put(f"/acl/assignments/{dnp(PARIS)}", escalation)
    assert refused.status_code == 403
    assert "cannot grant rights you do not hold" in refused.json()["error"]["message"].lower()
    # nothing was written
    assert api.get(f"/acl/assignments/{dnp(PARIS)}").json()["assignments"] == []


def test_assignment_may_grant_an_equal_or_lesser_role(client: TestClient) -> None:
    _delegate(client)
    api = Api(client).login("bmartin")
    lesser = {"assignments": [{"scope": "subtree", "role": HELPDESK_ROLE, "members": [BMARTIN]}]}
    assert api.put(f"/acl/assignments/{dnp(PARIS)}", lesser).status_code == 200
    equal = {"assignments": [{"scope": "subtree", "role": DELEGATE_ROLE, "members": [BMARTIN]}]}
    assert api.put(f"/acl/assignments/{dnp(PARIS)}", equal).status_code == 200


def _role_editor(client: TestClient) -> str:
    """Give bmartin a role that may edit roles, itself included, assigned on the base."""
    state = cast("AppState", cast("FastAPI", client.app).state.heracles)
    directory = cast("MemoryDirectory", state.directories["main"])
    role = f"cn=role-editor,ou=aclroles,{BASE}"
    directory.add(
        role,
        {
            "objectClass": [schema.OC.ACL_ROLE.encode()],
            "cn": [b"role-editor"],
            schema.ATTR.ACL_TEMPLATE: [b"0:user/user;rw,acl/aclRole;rw"],
        },
    )
    value = serialise_assignment(AclAssignment(3, AclScope.SUBTREE, role, (BMARTIN,))).encode()
    directory.modify(BASE, [Modification("add", schema.ATTR.ACL_ENTRY, [value])])
    return role


def test_role_edit_cannot_grant_rights_the_caller_does_not_hold(client: TestClient) -> None:
    role = _role_editor(client)
    api = Api(client).login("bmartin")
    path = f"/acl/roles/{dnp(role)}"
    escalation = {"templates": [template_to_json("0:all;rwcdm")]}
    refused = api.put(path, escalation)
    assert refused.status_code == 403, refused.text
    assert "all:rwcdm" in refused.json()["error"]["message"]
    assert api.get(path).json()["templates"][0]["raw"] == "0:user/user;rw,acl/aclRole;rw"
    # a change within the caller's own rights goes through
    lesser = {"templates": [template_to_json("0:user/user;r,acl/aclRole;rw")]}
    assert api.put(path, lesser).status_code == 200


def test_role_object_edit_cannot_grant_rights_the_caller_does_not_hold(
    client: TestClient,
) -> None:
    """The role type writes its templates through the generic object API."""
    role = _role_editor(client)
    api = Api(client).login("bmartin")
    path = f"/api/v2/objects/acl_role/{dnp(role)}"

    def patch(*templates: str) -> Any:
        body = {"tabs": {"main": {"values": {schema.ATTR.ACL_TEMPLATE: list(templates)}}}}
        return client.patch(path, json=body, headers=api.headers)

    refused = patch("0:all;rwcdm")
    assert refused.status_code == 422, refused.text
    assert "all:rwcdm" in refused.json()["error"]["fields"]["main"]
    assert patch("0:user/user;r,acl/aclRole;rw").status_code == 200


def test_revoked_assignment_takes_effect_in_other_sessions(client: TestClient) -> None:
    """An ACL change reaches every session at once, not when its cache expires."""
    _delegate(client)
    delegate = Api(TestClient(client.app, base_url="http://testserver")).login("bmartin")
    assert delegate.get(f"/acl/assignments/{dnp(PARIS)}").status_code == 200
    admin = Api(client).login("admin")
    kept = [
        {"scope": a["scope"], "role": a["role"], "members": [m["dn"] for m in a["members"]]}
        for a in admin.get(f"/acl/assignments/{dnp(BASE)}").json()["assignments"]
        if a["role"] != DELEGATE_ROLE
    ]
    assert admin.put(f"/acl/assignments/{dnp(BASE)}", {"assignments": kept}).status_code == 200
    assert delegate.get(f"/acl/assignments/{dnp(PARIS)}").status_code == 403


def test_super_admin_assigns_any_role(client: TestClient, admin: Api) -> None:
    payload = {"assignments": [{"scope": "subtree", "role": FULL_ADMIN_ROLE, "members": [BMARTIN]}]}
    saved = admin.put(f"/acl/assignments/{dnp(PARIS)}", payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["assignments"][0]["role"] == FULL_ADMIN_ROLE


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


def test_department_acl_tab_refuses_granting_above_the_caller(client: TestClient) -> None:
    """The tab writes through the generic object API: the core subset rule covers it."""
    editor_role = f"cn=tab-editor,ou=aclroles,{BASE}"
    state = cast("AppState", cast("FastAPI", client.app).state.heracles)
    directory = cast("MemoryDirectory", state.directories["main"])
    directory.add(
        editor_role,
        {
            "objectClass": [schema.OC.ACL_ROLE.encode()],
            "cn": [b"tab-editor"],
            schema.ATTR.ACL_TEMPLATE: [b"0:department/aclAssignment;rw,user/user;r"],
        },
    )
    directory.modify(
        BASE,
        [
            Modification(
                "add",
                schema.ATTR.ACL_ENTRY,
                [
                    serialise_assignment(
                        AclAssignment(4, AclScope.SUBTREE, editor_role, (BMARTIN,))
                    ).encode()
                ],
            )
        ],
    )
    api = Api(client).login("bmartin")
    paris = f"/api/v2/objects/department/{dnp(PARIS)}"
    escalation = {
        "tabs": {
            "acl": {
                "active": True,
                "values": {
                    "assignments": [
                        {
                            "index": 0,
                            "scope": "subtree",
                            "role": FULL_ADMIN_ROLE,
                            "members": [BMARTIN],
                            "user_filter": None,
                            "target_filter": None,
                        }
                    ]
                },
            }
        }
    }
    refused = client.patch(paris, json=escalation, headers=api.headers)
    assert refused.status_code == 422, refused.text
    error = refused.json()["error"]
    assert "cannot grant rights you do not hold" in error["fields"]["acl"].lower()
    assert "all:rwcdm" in error["fields"]["acl"]
    stored = Api(client).login("admin").get(f"/acl/assignments/{dnp(PARIS)}").json()
    assert stored["assignments"] == []


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


def test_config_put_refuses_invalid_values_with_the_offending_keys(admin: Api) -> None:
    bad = {
        "user_rdn": "anything",
        "password_default_hash": "foo",
        "default_shell": "bash",
        "timezone": "Mars",
        "cas_port": 0,
    }
    refused = admin.put("/config", {"changes": bad})
    assert refused.status_code == 422, refused.text
    assert set(refused.json()["error"]["fields"]) == set(bad)
    assert admin.get("/config").json()["exists"] is False  # nothing was written
    good = {
        "ogroup_rdn": "ou=og",
        "password_default_hash": "ssha512",
        "default_shell": "/bin/zsh",
        "timezone": "Europe/Paris",
        "cas_port": 8443,
    }
    saved = admin.put("/config", {"changes": good})
    assert saved.status_code == 200, saved.text
    fields = {f["key"]: f for f in saved.json()["fields"]}
    assert fields["ogroup_rdn"]["constraints"] == {"format": "rdn"}
    assert fields["cas_port"]["constraints"] == {"min": 1, "max": 65535}
    assert "ssha512" in fields["password_default_hash"]["options"]
    cross = admin.put("/config", {"changes": {"shells": ["/bin/sh"]}})
    assert cross.status_code == 422
    assert set(cross.json()["error"]["fields"]) == {"shells"}


def _script(directory: Path, name: str, body: str) -> str:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return name


@pytest.fixture
def scripts(tmp_path: Path) -> Path:
    directory = tmp_path / "scripts"
    directory.mkdir()
    return directory


@pytest.fixture
def hook_client(scripts: Path) -> Iterator[TestClient]:
    """Application whose demo administrator is a bootstrap administrator, with approved scripts."""
    settings = ApiSettings(
        admin_dns=[ADMIN],
        directory_labels={"main": "Demo directory"},
        plugins=PluginsSettings(enabled=["*"]),
        triggers=TriggersSettings(scripts_dir=scripts),
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": demo.build_demo_directory()})
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def hook_admin(hook_client: TestClient) -> Api:
    return Api(hook_client).login("admin")


def test_hooks_endpoint(hook_admin: Api, scripts: Path) -> None:
    ok = _script(scripts, "ok.sh", "true")
    view = hook_admin.get("/hooks").json()
    assert view["hooks"] == [] and "posixAccount" in view["tabs"] and "check" in view["modes"]
    assert view["scripts"] == [ok] and view["scripts_enabled"] is True
    saved = hook_admin.put(
        "/hooks",
        {
            "hooks": [
                {"tab": "user", "mode": "postcreate", "command": ok, "enabled": True},
                {"tab": "posixAccount", "mode": "premodify", "command": ok, "enabled": False},
            ],
            "display_output": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["display_output"] is True
    assert saved.json()["hooks"][1]["enabled"] is False
    bad = hook_admin.put("/hooks", {"hooks": [{"tab": "user", "mode": "nope", "command": ""}]})
    assert bad.status_code == 422
    assert set(bad.json()["error"]["fields"]) == {"hooks.0.mode", "hooks.0.command"}


def test_triggers_are_for_bootstrap_administrators_who_just_signed_in(
    admin: Api, hook_client: TestClient, hook_admin: Api
) -> None:
    item = {"tab": "user", "mode": "postcreate", "command": "ok.sh"}
    # config/config;w alone (the demo administrator is not a bootstrap administrator)
    refused = admin.put("/hooks", {"hooks": [item]})
    assert refused.status_code == 403, refused.text
    assert admin.get("/hooks").json()["can_write"] is False
    # a bootstrap administrator whose sign-in is old must confirm the password first
    state = cast("AppState", cast("FastAPI", hook_client.app).state.heracles)
    state.clock = lambda: time.time() + 3600
    stale = hook_admin.put("/hooks", {"hooks": [item]})
    assert stale.status_code == 403 and stale.json()["error"]["code"] == "reauth_required"


def test_a_shell_command_is_not_accepted_as_a_trigger(hook_admin: Api) -> None:
    for command in ("echo %uid%", "touch /tmp/x; id", "/bin/true", "../x.sh", "a b"):
        r = hook_admin.put(
            "/hooks", {"hooks": [{"tab": "user", "mode": "check", "command": command}]}
        )
        assert r.status_code == 422, command
        assert set(r.json()["error"]["fields"]) == {"hooks.0.command"}


def test_hook_runs_on_object_events(
    hook_client: TestClient, hook_admin: Api, scripts: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "marker"
    refuse = _script(scripts, "refuse.sh", f"echo no >{marker}; exit 1")
    hook_admin.put("/hooks", {"hooks": [{"tab": "user", "mode": "premodify", "command": refuse}]})
    r = hook_client.patch(
        f"/api/v2/objects/user/{dnp(BMARTIN)}",
        json={"tabs": {"main": {"active": True, "values": {"sn": "Changed"}}}},
        headers=hook_admin.headers,
    )
    assert r.status_code == 422, r.text
    assert marker.read_text().strip() == "no"
    after = hook_client.get(f"/api/v2/objects/user/{dnp(BMARTIN)}").json()
    assert after["tabs"]["main"]["values"]["sn"] == "Martin"


def test_hook_output_reaches_the_user(
    hook_client: TestClient, hook_admin: Api, scripts: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "marker"
    saved = _script(scripts, "saved.sh", f"touch {marker}; echo saved")
    oops = _script(scripts, "oops.sh", "echo oops >&2; exit 2")
    hook_admin.put(
        "/hooks",
        {
            "hooks": [
                {"tab": "user", "mode": "postmodify", "command": saved},
                {"tab": "user", "mode": "postmodify", "command": oops},
            ],
            "display_output": True,
        },
    )
    r = hook_client.patch(
        f"/api/v2/objects/user/{dnp(BMARTIN)}",
        json={"tabs": {"main": {"active": True, "values": {"sn": "Changed"}}}},
        headers=hook_admin.headers,
    )
    assert r.status_code == 200, r.text
    assert marker.exists()
    assert r.json()["messages"] == ["saved"]
    assert any("oops" in w for w in r.json()["warnings"])


def test_lock_triggers_run_on_lock_and_unlock(
    hook_client: TestClient, hook_admin: Api, scripts: Path, tmp_path: Path
) -> None:
    seen = tmp_path / "seen"
    hooks = [
        {
            "tab": "user",
            "mode": mode,
            "command": _script(scripts, f"{mode}.sh", f"echo {word} >>{seen}"),
        }
        for mode, word in (
            ("prelock", "pre"),
            ("postlock", "post"),
            ("preunlock", "upre"),
            ("postunlock", "upost"),
        )
    ]
    hook_admin.put("/hooks", {"hooks": hooks})
    locked = hook_client.post(f"/api/v2/users/{dnp(BMARTIN)}/lock", headers=hook_admin.headers)
    assert locked.status_code == 200, locked.text
    assert locked.json()["locked"] is True
    unlocked = hook_client.post(f"/api/v2/users/{dnp(BMARTIN)}/unlock", headers=hook_admin.headers)
    assert unlocked.json()["locked"] is False
    assert seen.read_text().split() == ["pre", "post", "upre", "upost"]


def test_failing_prelock_trigger_aborts_the_lock(
    hook_client: TestClient, hook_admin: Api, scripts: Path
) -> None:
    refuse = _script(scripts, "refuse.sh", "echo refused >&2; exit 1")
    hook_admin.put("/hooks", {"hooks": [{"tab": "user", "mode": "prelock", "command": refuse}]})
    r = hook_client.post(f"/api/v2/users/{dnp(BMARTIN)}/lock", headers=hook_admin.headers)
    assert r.status_code == 422, r.text
    assert "refused" in r.text


def test_health_checks_and_fix(admin: Api) -> None:
    results = {r["id"]: r for r in admin.get("/checks").json()}
    assert results["default_roles"]["status"] == "warning"
    assert results["default_roles"]["message_key"] == "default_roles.missing"
    assert results["default_roles"]["message_params"]["count"] == 3
    assert results["root_object"]["message_params"] == {"dn": BASE}
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
    assert admin.get("/tasks", kind="audit_task").json()["tasks"][0]["dn"] == task_dn
    assert admin.get("/tasks", status="Deactivated").json()["tasks"] == []

    queued = admin.post(f"/tasks/{dnp(task_dn)}/run")
    assert queued.status_code == 200 and queued.json()["queued"] is True
    assert admin.post(f"/tasks/{dnp('cn=none,' + BASE)}/run").status_code == 404
    retried = admin.post(f"/tasks/{dnp(task_dn)}/retry")
    assert retried.json()["retried"] == []
    helpdesk = Api(TestClient(build_demo_app(), base_url="http://testserver")).login("bmartin")
    assert helpdesk.post(f"/tasks/{dnp(task_dn)}/run").status_code in (403, 404)


def test_task_retry_requeues_failed_subtasks(client: TestClient, admin: Api) -> None:
    created = client.post(
        "/api/v2/objects/audit_task",
        json={
            "base": BASE,
            "tabs": {"main": {"active": True, "values": {"cn": "purge-audit"}}},
        },
        headers=admin.headers,
    )
    task_dn = created.json()["dn"]
    directory = cast("AppState", cast("FastAPI", client.app).state.heracles).directories["main"]
    failed_dn = f"cn=sub-failed,{task_dn}"
    done_dn = f"cn=sub-done,{task_dn}"
    for sub_dn, status in ((failed_dn, "Failed"), (done_dn, "Done")):
        directory.add(
            sub_dn,
            {
                "objectClass": [b"hrcTasksGranular"],
                "cn": [sub_dn.split(",")[0].split("=")[1].encode()],
                "hrcTasksGranularMaster": [task_dn.encode()],
                "hrcTasksGranularStatus": [status.encode()],
            },
        )
    row = admin.get("/tasks").json()["tasks"][0]
    assert row["subtasks"] == {"total": 2, "done": 1, "failed": 1}
    assert row["failed_subtasks"] == [failed_dn]

    retried = admin.post(f"/tasks/{dnp(task_dn)}/retry").json()
    assert retried["retried"] == [failed_dn]
    entry = directory.get(failed_dn)
    assert entry is not None and entry.text("hrcTasksGranularStatus") == "Activated"
    assert entry.text("hrcTasksGranularNextExec")
    untouched = directory.get(done_dn)
    assert untouched is not None and untouched.text("hrcTasksGranularStatus") == "Done"
    assert admin.get("/tasks").json()["tasks"][0]["subtasks"]["failed"] == 0


def test_user_list_counts_only_groups_the_caller_may_read() -> None:
    def counts(username: str) -> dict[str, int]:
        client = TestClient(build_demo_app(), base_url="http://testserver")
        Api(client).login(username)
        page = client.get(
            "/api/v2/objects/user", params={"base": BASE, "scope": "sub", "limit": 500}
        ).json()
        return {i["dn"]: i["groups_count"] for i in page["items"]}

    admin_view = counts("admin")
    assert any(n > 0 for n in admin_view.values())
    # helpdesk reads users but no groups: memberships must not leak through the count
    helpdesk_view = counts("helpdesk")
    assert helpdesk_view and all(n == 0 for n in helpdesk_view.values())


def test_group_list_counts_members_with_one_search_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_demo_app()
    client = TestClient(app, base_url="http://testserver")
    state = cast("AppState", app.state.heracles)
    directory = cast("MemoryDirectory", state.directories["main"])
    expected = {
        e.dn: len(e.texts("member"))
        for e in directory.search(BASE, "(objectClass=groupOfNames)", attrs=["member"])
    }
    assert len(expected) > 1 and any(expected.values())
    Api(client).login("admin")
    params = {"base": BASE, "scope": "sub", "limit": 500}
    client.get("/api/v2/objects/group", params=params)  # sessions, ACL resolution, caches

    calls: list[str] = []
    for name in ("get", "search"):
        original = getattr(directory, name)

        def counted(*args: Any, _name: str = name, _original: Any = original, **kw: Any) -> Any:
            calls.append(_name)
            return _original(*args, **kw)

        monkeypatch.setattr(directory, name, counted)
    page = client.get("/api/v2/objects/group", params=params).json()
    monkeypatch.undo()
    assert {i["dn"]: i["members_count"] for i in page["items"]} == expected
    # the listing search and one search for the counters, whatever the size of the page
    assert calls.count("get") == 0, calls
    assert calls.count("search") <= 3, calls

    # helpdesk reads users but no groups: no counter reveals the memberships
    other = TestClient(build_demo_app(), base_url="http://testserver")
    Api(other).login("helpdesk")
    rows = other.get("/api/v2/objects/group", params=params).json()["items"]
    assert all("members_count" not in i for i in rows)


def test_run_task_checks_the_rights_of_its_own_kind(
    client: TestClient, admin: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write rights on another task type do not allow running this task."""
    from heracles.acl import Rights
    from heracles.api.v2 import admin as admin_routes

    r = client.post(
        "/api/v2/objects/audit_task",
        json={"base": BASE, "tabs": {"main": {"active": True, "values": {"cn": "purge"}}}},
        headers=admin.headers,
    )
    assert r.status_code == 201, r.text
    task_dn = r.json()["dn"]

    def only_archive_tasks(_user: Any, _domain: Any, key: str, _dn: Any = None) -> Rights:
        return Rights.parse("rw" if "archive" in key.lower() else "r")

    monkeypatch.setattr(admin_routes, "rights_of", only_archive_tasks)
    assert admin.post(f"/tasks/{dnp(task_dn)}/run").status_code == 403
