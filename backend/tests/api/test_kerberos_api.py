"""API v2 integration tests for the Kerberos plugin tab on users."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"
PEOPLE = f"ou=people,{PARIS}"


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


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    orig_builder = demo.build_demo_directory

    def _build_demo_dir() -> MemoryDirectory:
        d = orig_builder()
        d.set_schema_object_classes(
            d.schema_object_classes() | {"krbprincipalaux", "krbticketpolicyaux"}
        )
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_includes_kerberos_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "kerberos" in tabs
    tab = tabs["kerberos"]
    assert tab["label"] == "Kerberos"
    assert tab["optional"] is True


def test_kerberos_api_flow(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    # Create user with kerberos tab
    payload = {
        "base": PARIS,
        "tabs": {
            "main": {
                "values": {
                    "uid": "krbuser",
                    "sn": "User",
                    "givenName": "Kerberos",
                }
            },
            "kerberos": {
                "values": {
                    "krbPrincipalName": "krbuser@EXAMPLE.COM",
                    "DISALLOW_FORWARDABLE": True,
                    "REQUIRES_PRE_AUTH": True,
                }
            },
        },
    }
    r = a.post("/objects/user", payload)
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    # Read back user
    r_get = a.get(f"/objects/user/{q(dn)}")
    assert r_get.status_code == 200
    data = r_get.json()
    assert "kerberos" in data["tabs"]
    values = data["tabs"]["kerberos"]["values"]
    assert values["krbPrincipalName"] == "krbuser@EXAMPLE.COM"
    assert values["DISALLOW_FORWARDABLE"] is True
    assert values["REQUIRES_PRE_AUTH"] is True
    assert values["DISALLOW_POSTDATED"] is False
    assert values["krbTicketFlags"] == 130

    # Patch ticket flags
    patch_payload = {
        "tabs": {
            "kerberos": {
                "values": {
                    "DISALLOW_FORWARDABLE": False,
                    "NEW_PRINC": True,
                }
            }
        }
    }
    r_patch = a.patch(f"/objects/user/{q(dn)}", patch_payload)
    assert r_patch.status_code == 200, r_patch.text
    patched = r_patch.json()
    assert patched["tabs"]["kerberos"]["values"]["DISALLOW_FORWARDABLE"] is False
    assert patched["tabs"]["kerberos"]["values"]["NEW_PRINC"] is True
    assert patched["tabs"]["kerberos"]["values"]["krbTicketFlags"] == 32896  # 0x8000 | 0x80
