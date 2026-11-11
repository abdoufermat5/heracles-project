"""``GET /api/v2/me/applications`` on the full application."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.demo import BASE
from heracles.server import create_full_app

PARIS = f"ou=paris,{BASE}"
BMARTIN = f"uid=bmartin,ou=people,{PARIS}"
CLASSES = ["hrcDesktopApplication", "hrcWebApplication", "hrcApplicationRights"]


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


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    directory = demo.build_demo_directory()
    directory.set_schema_object_classes([*directory.schema_object_classes(), *CLASSES])
    settings = ApiSettings(admin_dns=[])
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def create(admin: Api, type_name: str, tabs: dict[str, Any]) -> str:
    r = admin.post(f"/objects/{type_name}", {"base": BASE, "tabs": tabs})
    assert r.status_code == 201, r.text
    return str(r.json()["dn"])


def test_requires_authentication(app_client: TestClient) -> None:
    assert app_client.get("/api/v2/me/applications").status_code == 401


def test_user_sees_the_applications_of_their_roles(app_client: TestClient) -> None:
    admin = Api(app_client).login("admin")
    types = {t["name"] for t in admin.get("/types").json()}
    assert {"application", "web_application"} <= types
    role_tabs = {t["name"] for t in admin.get("/types/role").json()["tabs"]}
    assert "applications" in role_tabs

    terminal = create(
        admin,
        "application",
        {"main": {"values": {"cn": "terminal", "hrcApplicationTitle": "Terminal"}}},
    )
    wiki = create(
        admin,
        "web_application",
        {"main": {"values": {"cn": "wiki", "labeledURI": "https://wiki.example.com/"}}},
    )
    create(admin, "web_application", {"main": {"values": {"cn": "hidden", "labeledURI": "x:y"}}})
    create(
        admin,
        "role",
        {
            "main": {"values": {"cn": "staff", "roleOccupant": [BMARTIN]}},
            "applications": {"values": {"hrcApplicationAllowed": [wiki, terminal]}},
        },
    )

    user = Api(app_client).login("bmartin")
    r = user.get("/me/applications")
    assert r.status_code == 200, r.text
    apps = r.json()
    assert [(a["name"], a["type"]) for a in apps] == [
        ("terminal", "application"),
        ("wiki", "web_application"),
    ]
    assert apps[1]["url"] == "https://wiki.example.com/"
    assert apps[0]["title"] == "Terminal"

    nobody = Api(app_client).login("helpdesk")
    assert nobody.get("/me/applications").json() == []
