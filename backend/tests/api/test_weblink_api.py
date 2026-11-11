"""API v2 tests for the Weblink plugin."""

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
    directory.set_schema_object_classes([*directory.schema_object_classes(), "hrcWebLinkAccount"])
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_weblink_server_api(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")

    # Create server with weblink tab
    r = a.post(
        "/objects/server",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "api-srv",
                        "description": "API Gateway",
                    }
                },
                "weblink": {
                    "active": True,
                    "values": {
                        "hrcWebLinkProtocol": "https://",
                        "hrcWebLinkURL": "api.example.com",
                    },
                },
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    # Verify weblink tab
    r = a.get(f"/objects/server/{dn}")
    assert r.status_code == 200
    weblink_tab = r.json()["tabs"]["weblink"]
    assert weblink_tab["active"] is True
    assert weblink_tab["values"]["hrcWebLink"] == "https://api.example.com"

    # Cleanup
    r = a.delete(f"/objects/server/{dn}")
    assert r.status_code == 204
