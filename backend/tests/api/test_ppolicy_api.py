"""End-to-end API tests for the ppolicy plugin on the demo application."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles.api.app import AppState
from heracles.demo import BASE
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"
ASMITH = f"uid=asmith,ou=people,{PARIS}"
PPOLICIES = f"ou=ppolicies,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    """Small helper around TestClient handling CSRF and login."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        token = client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}

    def login(self, username: str, password: str = "heracles") -> Api:
        r = self.post(
            "/auth/login", {"directory": "main", "username": username, "password": password}
        )
        assert r.status_code == 200, r.text
        token = self.client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}
        return self

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def patch(self, path: str, body: Any) -> Any:
        return self.client.patch(f"/api/v2{path}", json=body, headers=self.headers)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v2{path}", headers=self.headers)


def demo_directory(client: TestClient) -> MemoryDirectory:
    app_state = cast(AppState, client.app.state.heracles)  # type: ignore[attr-defined]
    return cast(MemoryDirectory, app_state.directories["main"])


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    app = build_demo_app()
    state = cast(AppState, app.state.heracles)
    demo_dir = cast(MemoryDirectory, state.directories["main"])
    demo_dir.add(
        PPOLICIES,
        {"objectClass": [b"organizationalUnit"], "ou": [b"ppolicies"]},
    )
    with TestClient(app) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


# ------------------------------------------------------------- tests


def test_ppolicy_type_registered_and_descriptor(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    assert "ppolicy" in types
    assert types["ppolicy"]["category"] == "access"
    assert types["ppolicy"]["can_create"] is True

    # Check ppolicy descriptor
    desc = a.get("/types/ppolicy").json()
    assert desc["main_attr"] == "cn"
    assert desc["tabs"][0]["name"] == "main"
    section_labels = [s["label"] for s in desc["tabs"][0]["sections"]]
    assert "Properties" in section_labels
    assert "Expiration" in section_labels
    assert "Lockout" in section_labels

    # Check user descriptor includes ppolicy tab and it is not optional
    user_desc = a.get("/types/user").json()
    ppolicy_tab = next(t for t in user_desc["tabs"] if t["name"] == "ppolicy")
    assert ppolicy_tab["optional"] is False


def test_admin_creates_policy_and_assigns_to_user(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # 1. Admin creates a policy via POST /api/v2/objects/ppolicy
    r = a.post(
        "/objects/ppolicy",
        {
            "base": BASE,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "standard",
                        "description": "Standard corporate password policy",
                        "pwdMinLength": 10,
                        "pwdMaxAge": 90,
                        "pwdLockout": True,
                        "pwdMaxFailure": 5,
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    policy_dn = r.json()["dn"]
    assert policy_dn == f"cn=standard,{PPOLICIES}"

    # Read the created policy
    obj = a.get(f"/objects/ppolicy/{q(policy_dn)}").json()
    assert obj["tabs"]["main"]["values"]["cn"] == "standard"
    assert obj["tabs"]["main"]["values"]["pwdMinLength"] == 10
    assert obj["tabs"]["main"]["values"]["pwdMaxAge"] == 90
    assert obj["tabs"]["main"]["values"]["pwdLockout"] is True

    # 2. Assign policy to a user via PATCH /api/v2/objects/user/{dn}
    patch_res = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "ppolicy": {
                    "values": {
                        "pwdPolicySubentry": policy_dn,
                        "pwdReset": True,
                    }
                }
            }
        },
    )
    assert patch_res.status_code == 200, patch_res.text
    user_obj = patch_res.json()
    assert user_obj["tabs"]["ppolicy"]["values"]["pwdPolicySubentry"] == policy_dn
    assert user_obj["tabs"]["ppolicy"]["values"]["pwdReset"] is True

    # Verify subsequent GET loads the assigned policy
    user_get = a.get(f"/objects/user/{q(ASMITH)}").json()
    assert user_get["tabs"]["ppolicy"]["values"]["pwdPolicySubentry"] == policy_dn
    assert user_get["tabs"]["ppolicy"]["values"]["pwdReset"] is True


def test_unlock_hook_removes_pwd_account_locked_time(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    demo_dir = demo_directory(app_client)
    # Simulate user account being locked with pwdAccountLockedTime
    demo_dir.modify(
        ASMITH,
        [Modification("replace", "pwdAccountLockedTime", [b"20261107120000Z"])],
    )
    entry = demo_dir.get(ASMITH)
    assert entry is not None
    assert entry.text("pwdAccountLockedTime") == "20261107120000Z"

    # Admin calls POST /users/{dn}/unlock
    r = a.post(f"/users/{q(ASMITH)}/unlock")
    assert r.status_code == 200, r.text

    # Verify pwdAccountLockedTime was removed by the hook
    entry_after = demo_dir.get(ASMITH)
    assert entry_after is not None
    assert entry_after.get("pwdAccountLockedTime") == []


def test_user_ppolicy_tab_cannot_be_deactivated_via_api(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {"tabs": {"ppolicy": {"active": False}}},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation"
    assert "ppolicy" in err["fields"]
