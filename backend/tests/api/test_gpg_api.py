"""API v2 integration tests for the GPG plugin."""

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
        d.set_schema_object_classes(
            d.schema_object_classes() | {"hrcgpgaccount", "pgpkeyinfo", "pgpserverinfo"}
        )
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_includes_gpg_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "gpg" in tabs
    assert tabs["gpg"]["label"] == "GPG"
    assert tabs["gpg"]["optional"] is True


def test_types_includes_pgp_key_and_server_info(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.get("/types")
    assert r.status_code == 200
    types = {t["name"] for t in r.json()}
    assert "pgp_key" in types
    assert "pgp_server_info" in types


def test_gpg_flow_via_api(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # 1. Create a PGP key object
    key_payload = {
        "base": PARIS,
        "tabs": {
            "main": {
                "values": {
                    "pgpCertID": "A1B2C3D4E5F67890",
                    "pgpUserID": "Alice API <alice@api.test>",
                }
            }
        },
    }
    r_key = a.post("/objects/pgp_key", key_payload)
    assert r_key.status_code == 201, r_key.text
    key_dn = r_key.json()["dn"]

    # 2. Create user referencing key
    user_payload = {
        "base": PARIS,
        "tabs": {
            "main": {
                "values": {
                    "uid": "gpguser",
                    "sn": "User",
                    "givenName": "GPG",
                }
            },
            "gpg": {
                "active": True,
                "values": {
                    "hrcUserKeyDN": [key_dn],
                },
            },
        },
    }
    r_user = a.post("/objects/user", user_payload)
    assert r_user.status_code == 201, r_user.text
    user_dn = r_user.json()["dn"]

    # 3. Read back user
    r_get = a.get(f"/objects/user/{q(user_dn)}")
    assert r_get.status_code == 200
    data = r_get.json()
    assert "gpg" in data["tabs"]
    assert data["tabs"]["gpg"]["values"]["hrcUserKeyDN"] == [key_dn]
    assert "A1B2C3D4E5F67890" in data["tabs"]["gpg"]["values"]["gpgSummary"]
