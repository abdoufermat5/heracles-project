"""API v2 integration tests for Postfix service tab."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import heracles_plugins.postfix as postfix
import heracles_plugins.systems as systems
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
            "ieee802Device",
            "device",
            "fdServer",
            "fdPostfixServer",
            "ipHost",
            "fdNetworkInterface",
        ]
    )
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema = {c.lower() for c in d.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema)
    registry.register_plugin(postfix.plugin(), schema)

    settings = ApiSettings(
        admin_dns=[],
        directory_labels={"main": "Demo directory"},
        enable_docs=True,
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": d}, registry=registry, load_plugins=False)
    return TestClient(app)


def test_postfix_api_flow(app_client: TestClient) -> None:
    client = Api(app_client).login("admin")

    # Verify type description contains postfix tab
    r = client.get("/types/server")
    assert r.status_code == 200
    tabs = {t["name"]: t for t in r.json()["tabs"]}
    assert "postfix" in tabs
    assert tabs["postfix"]["optional"] is True

    # Create server with postfix tab
    r = client.post(
        "/objects/server",
        {
            "base": f"ou=paris,{demo.BASE}",
            "tabs": {
                "main": {"values": {"cn": "postfix-srv"}},
                "postfix": {
                    "active": True,
                    "values": {
                        "postfixMyHostname": "smtp.paris.example.com",
                        "postfixMyDomain": "paris.example.com",
                        "postfixMessageSizeLimit": 20971520,
                        "fdPostfixCatchallTable": [
                            {
                                "fdCatchallTableDomain": "paris.example.com",
                                "fdCatchallTableRecipient": "catchall@paris.example.com",
                            }
                        ],
                    },
                },
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    # Read server
    r = client.get(f"/objects/server/{quote(dn, safe='')}")
    assert r.status_code == 200
    data = r.json()
    assert data["tabs"]["postfix"]["active"] is True
    assert data["tabs"]["postfix"]["values"]["postfixMyHostname"] == "smtp.paris.example.com"
    assert data["tabs"]["postfix"]["values"]["postfixMessageSizeLimit"] == 20971520
    assert data["tabs"]["postfix"]["values"]["fdPostfixCatchallTable"] == [
        {
            "fdCatchallTableDomain": "paris.example.com",
            "fdCatchallTableRecipient": "catchall@paris.example.com",
        }
    ]

    # Update server
    r = client.patch(
        f"/objects/server/{quote(dn, safe='')}",
        {
            "tabs": {
                "postfix": {
                    "values": {
                        "postfixMessageSizeLimit": 10485760,
                    }
                }
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["tabs"]["postfix"]["values"]["postfixMessageSizeLimit"] == 10485760

    # Delete server
    r = client.delete(f"/objects/server/{quote(dn, safe='')}")
    assert r.status_code == 204
