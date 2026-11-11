"""API v2 integration tests for the physical key plugin tab on users."""

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
        d.set_schema_object_classes(d.schema_object_classes() | {"hrcphysicalkey"})
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_includes_physical_key_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "physical_key" in tabs
    tab = tabs["physical_key"]
    assert tab["label"] == "Physical key"
    assert tab["optional"] is True


def test_physical_key_api_flow(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    payload = {
        "base": PARIS,
        "tabs": {
            "main": {
                "values": {
                    "uid": "keycarduser",
                    "sn": "Keycard",
                    "givenName": "User",
                }
            },
            "physical_key": {
                "active": True,
                "values": {
                    "hrcPhysicalKeyType": "rfid",
                    "hrcPhysicalKeyValue": "CARD-987654",
                },
            },
        },
    }
    r = a.post("/objects/user", payload)
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    r_get = a.get(f"/objects/user/{q(dn)}")
    assert r_get.status_code == 200
    data = r_get.json()
    assert "physical_key" in data["tabs"]
    assert data["tabs"]["physical_key"]["values"]["hrcPhysicalKeyType"] == "rfid"
    assert data["tabs"]["physical_key"]["values"]["hrcPhysicalKeyValue"] == "CARD-987654"

    # Patch badge value
    patch_payload = {
        "tabs": {
            "physical_key": {
                "values": {
                    "hrcPhysicalKeyValue": "CARD-112233",
                }
            }
        }
    }
    r_patch = a.patch(f"/objects/user/{q(dn)}", patch_payload)
    assert r_patch.status_code == 200, r_patch.text
    patched = r_patch.json()
    assert patched["tabs"]["physical_key"]["values"]["hrcPhysicalKeyValue"] == "CARD-112233"
