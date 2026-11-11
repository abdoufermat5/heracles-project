"""API v2 tests for the IPMI plugin."""

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
    directory.set_schema_object_classes([*directory.schema_object_classes(), "hrcIpmiClient"])
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_ipmi_server_api(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")

    # Create server with ipmi tab
    r = a.post(
        "/objects/server",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "ipmi-srv",
                        "description": "IPMI Managed Server",
                    }
                },
                "ipmi": {
                    "active": True,
                    "values": {
                        "hrcIpmiIP": "192.168.1.100",
                        "hrcIpmiLogin": "admin",
                        "hrcIpmiPassword": "ipmipassword",
                    },
                },
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    # Verify ipmi tab over API
    r = a.get(f"/objects/server/{dn}")
    assert r.status_code == 200
    ipmi_tab = r.json()["tabs"]["ipmi"]
    assert ipmi_tab["active"] is True
    assert ipmi_tab["values"]["hrcIpmiIP"] == "192.168.1.100"
    assert ipmi_tab["values"]["hrcIpmiLogin"] == "admin"
    # Password must not be leaked over API
    assert ipmi_tab["values"].get("hrcIpmiPassword") is None

    # Cleanup
    r = a.delete(f"/objects/server/{dn}")
    assert r.status_code == 204
