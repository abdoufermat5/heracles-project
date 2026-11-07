"""DNS plugin through API v2 on the in-memory demo directory."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.demo import BASE
from heracles.server import create_full_app

DNS_OU = f"ou=dns,{BASE}"
ZONE_DN = f"zoneName=example.com,{DNS_OU}"


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
    directory = demo.build_demo_directory()
    directory.set_schema_object_classes([*directory.schema_object_classes(), "dNSZone"])
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def rec(name: str, rtype: str, value: str) -> dict[str, str]:
    return {"name": name, "type": rtype, "value": value}


BODY: dict[str, Any] = {
    "base": BASE,
    "tabs": {
        "main": {
            "values": {
                "zoneName": "example.com",
                "soaPrimary": "ns1.example.com",
                "soaMail": "hostmaster@example.com",
                "reverseZones": ["2.0.192.in-addr.arpa"],
                "dnsRecord": [
                    rec("@", "NS", "ns1.example.com"),
                    rec("ns1", "A", "192.0.2.1"),
                    rec("www", "A", "192.0.2.10"),
                ],
            }
        }
    },
}


def test_type_is_listed_and_described(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    assert types["dns_zone"]["category"] == "network"
    desc = a.get("/types/dns_zone").json()
    assert desc["main_attr"] == "zoneName"
    names = {at["name"] for s in desc["tabs"][0]["sections"] for at in s["attributes"]}
    assert {"zoneName", "soaPrimary", "soaSerial", "reverseZones", "dnsRecord"} <= names
    assert "dns_view" in types  # the demo schema includes the view classes


def test_admin_creates_and_patches_zone(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")
    r = a.post("/objects/dns_zone", BODY)
    assert r.status_code == 201, r.text
    assert r.json()["dn"] == ZONE_DN

    obj = a.get(f"/objects/dns_zone/{q(ZONE_DN)}").json()
    values = obj["tabs"]["main"]["values"]
    assert values["soaPrimary"] == "ns1.example.com."
    assert values["soaMail"] == "hostmaster.example.com."
    assert values["reverseZones"] == ["2.0.192.in-addr.arpa"]
    assert [r["name"] for r in values["dnsRecord"]] == ["@", "ns1", "www"]
    assert "w" in obj["acl"]["main"]["attributes"]["dnsRecord"]
    serial = values["soaSerial"]
    assert len(serial) == 10

    assert a.post(f"/objects/dns_zone/{q(ZONE_DN)}/lock").status_code == 200
    r = a.patch(
        f"/objects/dns_zone/{q(ZONE_DN)}",
        {
            "tabs": {
                "main": {
                    "values": {"dnsRecord": [*values["dnsRecord"], rec("api", "A", "192.0.2.20")]}
                }
            }
        },
    )
    assert r.status_code == 200, r.text
    patched = r.json()["tabs"]["main"]["values"]
    assert [r["name"] for r in patched["dnsRecord"]] == ["@", "api", "ns1", "www"]
    assert int(patched["soaSerial"]) == int(serial) + 1
    assert a.delete(f"/objects/dns_zone/{q(ZONE_DN)}/lock").status_code == 204

    page = a.get("/objects/dns_zone", base=BASE, scope="sub").json()
    assert ZONE_DN in [i["dn"] for i in page["items"]]

    assert a.delete(f"/objects/dns_zone/{q(ZONE_DN)}").status_code == 204
    assert a.get(f"/objects/dns_zone/{q(ZONE_DN)}").status_code == 404


def test_validation_error_is_reported_on_records(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")
    values: dict[str, Any] = {
        **BODY["tabs"]["main"]["values"],
        "dnsRecord": [rec("www", "A", "nope")],
    }
    body = {"base": BASE, "tabs": {"main": {"values": values}}}
    r = a.post("/objects/dns_zone", body)
    assert r.status_code == 422, r.text
    assert "main.dnsRecord" in r.text


def test_regular_user_cannot_create_zone(app_client: TestClient) -> None:
    a = Api(app_client).login("bmartin")
    r = a.post("/objects/dns_zone", BODY)
    assert r.status_code == 403, r.text
