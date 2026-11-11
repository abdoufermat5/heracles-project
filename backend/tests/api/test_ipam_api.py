"""API v2 tests for the IPAM plugin."""

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
        [*directory.schema_object_classes(), "hrcIpamVlan", "hrcIpamSubnet"]
    )
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_ipam_vlan_and_subnet_api_flow(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")

    # 1. Create VLAN
    r = a.post(
        "/objects/ipamVlan",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "dmz-vlan",
                        "hrcIpamVlanInnerId": 50,
                        "description": "DMZ network",
                        "hrcIpamActive": True,
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    vlan_dn = r.json()["dn"]
    assert "cn=dmz-vlan" in vlan_dn

    # 2. Get VLAN
    r = a.get(f"/objects/ipamVlan/{vlan_dn}")
    assert r.status_code == 200
    assert r.json()["tabs"]["main"]["values"]["hrcIpamVlanInnerId"] == 50

    # 3. Create Subnet referencing VLAN
    r = a.post(
        "/objects/ipamSubnet",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "dmz-subnet",
                        "hrcIpamSubnetCIDR": "192.168.50.0/24",
                        "hrcIpamVlanDN": vlan_dn,
                        "description": "DMZ Subnet",
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    subnet_dn = r.json()["dn"]

    # 4. Search Subnets
    r = a.get("/objects/ipamSubnet", base=PARIS, q="192.168.50.0/24")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(item["dn"] == subnet_dn for item in items)

    # 5. Delete Subnet and VLAN
    r = a.delete(f"/objects/ipamSubnet/{subnet_dn}")
    assert r.status_code == 204

    r = a.delete(f"/objects/ipamVlan/{vlan_dn}")
    assert r.status_code == 204
