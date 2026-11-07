"""API v2 tests for the Autofs5 plugin."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from heracles.api.settings import ApiSettings
from heracles.demo import BASE, build_demo_directory
from heracles.server import create_full_app

PARIS = f"ou=paris,{BASE}"


class Api:
    """Small helper around TestClient handling CSRF and login."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        token = client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}

    def login(self, username: str, password: str = "heracles") -> Api:
        r = self.post(
            "/auth/login",
            {"directory": "main", "username": username, "password": password},
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
def app_client() -> Iterator[TestClient]:
    directory = build_demo_directory()
    directory.set_schema_object_classes(
        [*directory.schema_object_classes(), "automountMap", "automount"]
    )
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_autofs_api_flow_and_tree(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")

    # 1. Create Automount Map
    r = a.post(
        "/objects/automountMap",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "ou": "auto.direct",
                        "description": "Direct mounts",
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    map_dn = r.json()["dn"]
    assert "ou=auto.direct" in map_dn

    # 2. Create child Automount Entry
    r = a.post(
        "/objects/automount",
        {
            "base": map_dn,
            "tabs": {
                "main": {
                    "values": {
                        "automountKey": "/mnt/nfs",
                        "automountInformation": "-fstype=nfs4,rw nas:/data",
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    entry_dn = r.json()["dn"]
    assert "/mnt/nfs" in entry_dn

    # 3. Call tree endpoint
    r = a.get("/autofs/tree", dn=map_dn)
    assert r.status_code == 200, r.text
    tree = r.json()
    assert len(tree) == 1
    assert tree[0]["type"] == "automountMap"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["label"] == "/mnt/nfs"

    # 4. Delete Map (which cascades to entry)
    r = a.delete(f"/objects/automountMap/{map_dn}")
    assert r.status_code == 204
