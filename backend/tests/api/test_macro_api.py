"""API tests for the Macro plugin."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


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
def app_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    orig_builder = demo.build_demo_directory

    def _build_demo_dir() -> MemoryDirectory:
        d = orig_builder()
        d.set_schema_object_classes(
            d.schema_object_classes() | {"hrcphonemacro", "hrcphonemacrouser"}
        )
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_has_macro_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    u_desc = a.get("/types/user").json()
    u_tabs = {t["name"]: t for t in u_desc["tabs"]}
    assert "macro" in u_tabs
    assert u_tabs["macro"]["optional"] is True
    assert u_tabs["macro"]["label"] == "Macro"


def test_types_list_has_phone_macro(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    types_res = a.get("/types").json()
    names = {t["name"]: t for t in types_res}
    assert "phone_macro" in names
    assert names["phone_macro"]["label"] == "Phone macro"


def test_create_and_patch_user_macro(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    res = a.post(
        "/objects/user",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "active": True,
                    "values": {"uid": "muser", "givenName": "Macro", "sn": "User"},
                },
                "macro": {
                    "active": True,
                    "values": {
                        "hrcPhoneMacroContent": "stdexten",
                        "hrcPhoneMacroParameter": "100",
                    },
                },
            },
        },
    )
    assert res.status_code == 201, res.text
    dn = res.json()["dn"]

    read_res = a.get(f"/objects/user/{q(dn)}")
    assert read_res.status_code == 200
    tab = read_res.json()["tabs"]["macro"]
    assert tab["values"]["hrcPhoneMacroContent"] == "stdexten"
    assert tab["values"]["hrcPhoneMacroParameter"] == "100"

    patch_res = a.patch(
        f"/objects/user/{q(dn)}",
        {
            "tabs": {
                "macro": {
                    "active": True,
                    "values": {
                        "hrcPhoneMacroContent": "vm-check",
                    },
                }
            }
        },
    )
    assert patch_res.status_code == 200
    tab = patch_res.json()["tabs"]["macro"]
    assert tab["values"]["hrcPhoneMacroContent"] == "vm-check"
