"""API v2 tests for the Netgroups plugin."""

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
    directory.set_schema_object_classes([*directory.schema_object_classes(), "nisNetgroup"])
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_netgroup_api_flow(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")

    # 1. Create Netgroup
    r = a.post(
        "/objects/netgroup",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "qa-team",
                        "description": "QA Engineers",
                        "nisNetgroupTriple": ["(-,tester1,)"],
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    ng_dn = r.json()["dn"]
    assert "cn=qa-team" in ng_dn

    # 2. Get Netgroup
    r = a.get(f"/objects/netgroup/{ng_dn}")
    assert r.status_code == 200
    assert r.json()["tabs"]["main"]["values"]["cn"] == "qa-team"
    assert "(-,tester1,)" in r.json()["tabs"]["main"]["values"]["nisNetgroupTriple"]

    # 3. Search Netgroups
    r = a.get("/objects/netgroup", base=PARIS, q="qa-team")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(item["dn"] == ng_dn for item in items)

    # 4. Delete Netgroup
    r = a.delete(f"/objects/netgroup/{ng_dn}")
    assert r.status_code == 204
