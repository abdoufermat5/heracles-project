"""API v2 integration tests for Calendar calendar resources."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import heracles_plugins.calendar_resources as calendar_resources
from heracles import demo
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.server import ApiSettings, create_full_app


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
def app_client() -> TestClient:
    d = demo.build_demo_directory()
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            "hrcCalendarResource",
            "inetOrgPerson",
            "organizationalUnit",
        ]
    )
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema = {c.lower() for c in d.schema_object_classes()}
    registry.register_plugin(calendar_resources.plugin(), schema)

    settings = ApiSettings(
        admin_dns=[],
        directory_labels={"main": "Demo directory"},
        enable_docs=True,
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": d}, registry=registry, load_plugins=False)
    return TestClient(app)


def test_calendar_api_flow(app_client: TestClient) -> None:
    client = Api(app_client).login("admin")

    # Verify type description contains calendar_resource
    r = client.get("/types/calendar_resource")
    assert r.status_code == 200
    desc = r.json()
    assert desc["name"] == "calendar_resource"
    assert desc["category"] == "mail"

    # Create calendar resource
    r = client.post(
        "/objects/calendar_resource",
        {
            "base": f"ou=paris,{demo.BASE}",
            "tabs": {
                "main": {
                    "values": {
                        "uid": "boardroom",
                        "mail": "boardroom@paris.example.com",
                        "description": "Boardroom Paris",
                        "hrcResourceKind": "location",
                        "hrcResourceMultipleBookings": 0,
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    # Read calendar resource
    r = client.get(f"/objects/calendar_resource/{quote(dn, safe='')}")
    assert r.status_code == 200
    data = r.json()
    assert data["tabs"]["main"]["values"]["uid"] == "boardroom"
    assert data["tabs"]["main"]["values"]["mail"] == "boardroom@paris.example.com"
    assert data["tabs"]["main"]["values"]["hrcResourceKind"] == "location"

    # Update calendar resource
    r = client.patch(
        f"/objects/calendar_resource/{quote(dn, safe='')}",
        {
            "tabs": {
                "main": {
                    "values": {
                        "description": "Updated boardroom description",
                    }
                }
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["tabs"]["main"]["values"]["description"] == "Updated boardroom description"

    # Delete calendar resource
    r = client.delete(f"/objects/calendar_resource/{quote(dn, safe='')}")
    assert r.status_code == 204
