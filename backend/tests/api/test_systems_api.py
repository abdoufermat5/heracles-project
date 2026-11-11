"""API v2: create a server with two interfaces as admin (demo app + systems schema)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles.api.settings import ApiSettings
from heracles.demo import BASE, build_demo_directory
from heracles.server import create_full_app

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
def app_client() -> Iterator[TestClient]:
    directory = build_demo_directory()
    directory.set_schema_object_classes(
        [
            *directory.schema_object_classes(),
            "ieee802Device",
            "device",
            "hrcServer",
            "hrcWorkstation",
            "hrcTerminal",
            "hrcPrinter",
            "hrcPhone",
            "hrcMobilePhone",
            "hrcNetworkInterface",
            "ipHost",
        ]
    )
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_create_server_with_two_interfaces(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    assert {"server", "workstation", "printer", "component", "mobile_phone"} <= types.keys()
    assert types["server"]["category"] == "systems"

    r = a.post(
        "/objects/server",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "web1",
                        "description": "Front web server",
                        "l": "Paris",
                        "networkInterfaces": [
                            {
                                "cn": "eth0",
                                "macAddress": "AA:BB:CC:DD:EE:01",
                                "ipHostNumber": ["10.1.0.10", "2001:db8::10"],
                                "hrcNetworkInterfaceVlanTagged": False,
                            },
                            {"cn": "eth1", "macAddress": "aa:bb:cc:dd:ee:02"},
                        ],
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]
    assert dn == f"cn=web1,ou=servers,ou=systems,{PARIS}"

    obj = a.get(f"/objects/server/{q(dn)}").json()
    values = obj["tabs"]["main"]["values"]
    assert values["hrcMode"] is False
    interfaces = values["networkInterfaces"]
    assert [i["cn"] for i in interfaces] == ["eth0", "eth1"]
    assert interfaces[0]["macAddress"] == "aa:bb:cc:dd:ee:01"
    assert interfaces[0]["ipHostNumber"] == ["10.1.0.10", "2001:db8::10"]

    found = a.get("/objects/server", base=PARIS, scope="sub", q="10.1.0.10").json()
    assert [i["dn"] for i in found["items"]] == [dn]

    # a second system cannot reuse the address
    r = a.post(
        "/objects/workstation",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "ws1",
                        "networkInterfaces": [{"cn": "eth0", "ipHostNumber": ["10.1.0.10"]}],
                    }
                }
            },
        },
    )
    assert r.status_code == 422, r.text
    assert "main.networkInterfaces" in r.json()["error"]["fields"]

    assert a.delete(f"/objects/server/{q(dn)}").status_code == 204
    assert a.get(f"/objects/server/{q(dn)}").status_code == 404
