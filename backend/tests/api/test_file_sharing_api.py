"""API tests for the File sharing plugin."""

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
    """Helper around TestClient handling CSRF and login."""

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
        d.set_schema_object_classes(d.schema_object_classes() | {"hrcfilesharingaccount"})
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_has_file_sharing_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "file_sharing" in tabs
    assert tabs["file_sharing"]["optional"] is True
    assert tabs["file_sharing"]["label"] == "File sharing"


def test_create_and_read_user_with_file_sharing(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    res = a.post(
        "/objects/user",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "active": True,
                    "values": {"uid": "ncuser", "givenName": "Cloud", "sn": "User"},
                },
                "file_sharing": {
                    "active": True,
                    "values": {
                        "hrcFileSharingQuota": "20 GB",
                        "hrcFileSharingHomeFolder": "/srv/cloud/ncuser",
                    },
                },
            },
        },
    )
    assert res.status_code == 201, res.text
    dn = res.json()["dn"]

    read_res = a.get(f"/objects/user/{q(dn)}")
    assert read_res.status_code == 200
    tab = read_res.json()["tabs"]["file_sharing"]
    assert tab["active"] is True
    assert tab["values"]["hrcFileSharingQuota"] == "20 GB"
    assert tab["values"]["hrcFileSharingHomeFolder"] == "/srv/cloud/ncuser"
