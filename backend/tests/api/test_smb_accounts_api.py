"""SMB plugin through API v2 on the demo application (schema extended in the test)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.server import build_demo_app

DOMAIN_SID = "S-1-5-21-1-2-3"


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


@pytest.fixture
def smb_client() -> Iterator[TestClient]:
    with TestClient(build_demo_app()) as client:
        yield client


def test_demo_offers_smb() -> None:
    with TestClient(build_demo_app()) as client:
        a = Api(client).login("admin")
        names = {t["name"] for t in a.get("/types").json()}
        assert "smb_domain" in names
        tabs = [t["name"] for t in a.get("/types/user").json()["tabs"]]
        assert "smb" in tabs
        workstation_tabs = [t["name"] for t in a.get("/types/workstation").json()["tabs"]]
        assert "smb" in workstation_tabs


def test_domain_and_user_flow(smb_client: TestClient) -> None:
    a = Api(smb_client).login("admin")
    names = {t["name"] for t in a.get("/types").json()}
    assert "smb_domain" in names
    assert "smb" in [t["name"] for t in a.get("/types/user").json()["tabs"]]
    assert "smb" in [t["name"] for t in a.get("/types/posix_group").json()["tabs"]]

    r = a.post(
        "/objects/smb_domain",
        {
            "base": demo.BASE,
            "tabs": {"main": {"values": {"sambaDomainName": "CORP", "sambaSID": DOMAIN_SID}}},
        },
    )
    assert r.status_code == 201, r.text

    body = {
        "base": demo.BASE,
        "tabs": {
            "main": {
                "values": {
                    "uid": "wuser",
                    "givenName": "W",
                    "sn": "User",
                    "userPassword": "Str0ng-Passw0rd!x",
                }
            },
            "posix": {"active": True},
            "smb": {"active": True, "values": {"flag_pwdNeverExpires": True}},
        },
    }
    r = a.post("/objects/user", body)
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]
    obj = a.get(f"/objects/user/{q(dn)}").json()
    values = obj["tabs"]["smb"]["values"]
    assert values["sambaSID"].startswith(DOMAIN_SID + "-")
    assert values["sambaDomainName"] == "CORP"
    assert values["sambaAcctFlags"] == "[UX         ]"
    assert values["flag_pwdNeverExpires"] is True
    assert values["sambaNTPassword"] is None  # hashes never leave the server
    assert values["sambaLMPassword"] is None

    r = a.patch(f"/objects/user/{q(dn)}", {"tabs": {"smb": {"values": {"sambaLogonHours": "zz"}}}})
    assert r.status_code == 422
    assert "smb.sambaLogonHours" in r.json()["error"]["fields"]


def test_missing_domain_is_reported_on_the_smb_tab(smb_client: TestClient) -> None:
    admin = Api(smb_client).login("admin")
    body = {
        "base": demo.BASE,
        "tabs": {
            "main": {"values": {"uid": "wuser", "givenName": "W", "sn": "User"}},
            "posix": {"active": True},
            "smb": {"active": True},
        },
    }
    r = admin.post("/objects/user", body)
    assert r.status_code == 422  # no domain configured: reported on the smb tab
    assert "smb.sambaDomainName" in r.json()["error"]["fields"]
