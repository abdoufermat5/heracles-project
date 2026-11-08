"""API v2 tests: object templates."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles.demo import BASE
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
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
    with TestClient(build_demo_app()) as client:
        yield client


@pytest.fixture
def admin(app_client: TestClient) -> Api:
    return Api(app_client).login("admin")


STAFF_BODY: dict[str, Any] = {
    "name": "staff",
    "base": BASE,
    "tabs": {
        "main": {
            "active": True,
            "values": {
                "uid": "%s[0,1]l|givenName%%l|sn%",
                "mail": "%uid%@heracles.test",
                "description": "Staff of %o%",
            },
        }
    },
}


def make_staff(admin: Api) -> str:
    r = admin.post("/types/user/templates", STAFF_BODY)
    assert r.status_code == 201, r.text
    return str(r.json()["dn"])


def test_template_crud(admin: Api) -> None:
    dn = make_staff(admin)
    assert dn == f"cn=staff,ou=templates,ou=people,{BASE}"
    listed = admin.get("/types/user/templates").json()
    assert listed == [{"dn": dn, "name": "staff", "type": "user", "base": BASE}]
    assert admin.get("/types/group/templates").json() == []
    body = admin.get(f"/types/user/templates/{q(dn)}").json()
    assert body["tabs"]["main"]["values"]["uid"] == "%s[0,1]l|givenName%%l|sn%"
    assert body["tabs"]["main"]["active"] is True

    r = admin.patch(
        f"/types/user/templates/{q(dn)}",
        {"tabs": {"main": {"values": {"mail": "", "employeeType": "staff"}}}},
    )
    assert r.status_code == 200, r.text
    assert "mail" not in r.json()["tabs"]["main"]["values"]
    assert r.json()["tabs"]["main"]["values"]["employeeType"] == "staff"

    r = admin.patch(f"/types/user/templates/{q(dn)}", {"name": "employees"})
    assert r.status_code == 200
    new_dn = r.json()["dn"]
    assert new_dn.startswith("cn=employees,")
    assert admin.delete(f"/types/user/templates/{q(new_dn)}").status_code == 204
    assert admin.get(f"/types/user/templates/{q(new_dn)}").status_code == 404


def test_template_validation_errors(admin: Api) -> None:
    r = admin.post(
        "/types/user/templates",
        {"name": "bad", "base": BASE, "tabs": {"main": {"values": {"uid": "100% sure"}}}},
    )
    assert r.status_code == 422
    assert "main.uid" in r.json()["error"]["fields"]
    assert admin.post("/types/department/templates", {"name": "x", "base": BASE}).status_code == 422
    assert admin.post("/types/nope/templates", {"name": "x", "base": BASE}).status_code == 404
    assert make_staff(admin)
    assert admin.post("/types/user/templates", STAFF_BODY).status_code == 409


def test_fields_preview_and_create_from_template(admin: Api) -> None:
    dn = make_staff(admin)
    fields = admin.get(f"/types/user/templates/{q(dn)}/fields").json()["fields"]
    assert fields["main"] == ["sn", "givenName", "o"]

    values = {"main": {"givenName": "Zoé", "sn": "Müller", "o": "Acme"}}
    preview = admin.post(f"/types/user/templates/{q(dn)}/preview", {"values": values})
    assert preview.status_code == 200, preview.text
    assert preview.json()["tabs"]["main"]["uid"] == "zmüller"
    assert preview.json()["tabs"]["main"]["mail"] == "zmüller@heracles.test"

    missing = admin.post(
        f"/types/user/templates/{q(dn)}/preview", {"values": {"main": {"sn": "Doe"}}}
    )
    assert missing.status_code == 422
    assert "main.givenName" in missing.json()["error"]["fields"]

    plain = {"main": {"givenName": "Zoe", "sn": "Moulin", "o": "Acme"}}
    r = admin.post(
        "/objects/user",
        {"base": PARIS, "template": dn, "tabs": {t: {"values": v} for t, v in plain.items()}},
    )
    assert r.status_code == 201, r.text
    created = r.json()["dn"]
    assert created == f"uid=zmoulin,ou=people,{PARIS}"
    obj = admin.get(f"/objects/user/{q(created)}").json()
    assert obj["tabs"]["main"]["values"]["mail"] == "zmoulin@heracles.test"
    assert obj["tabs"]["main"]["values"]["description"] == "Staff of Acme"

    # a second user with the same names gets the next free login
    r = admin.post(
        "/objects/user",
        {"base": PARIS, "template": dn, "tabs": {"main": {"values": plain["main"]}}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["dn"] == f"uid=zmoulin1,ou=people,{PARIS}"


def test_templates_are_invisible_in_listings(admin: Api) -> None:
    make_staff(admin)
    for scope in ("one", "sub"):
        users = admin.get("/objects/user", base=BASE, scope=scope).json()
        assert all("templates" not in item["dn"] for item in users["items"])
    assert admin.get("/objects/group", base=BASE, scope="sub").json()["total"] == 2


def test_template_acl(app_client: TestClient, admin: Api) -> None:
    dn = make_staff(admin)
    user = Api(app_client).login("bmartin")
    assert user.get("/types/user/templates").json() == []
    assert user.get(f"/types/user/templates/{q(dn)}").status_code == 403
    assert user.post("/types/user/templates", STAFF_BODY).status_code == 403
    assert user.delete(f"/types/user/templates/{q(dn)}").status_code == 403


def test_descriptors_flag_template_support_and_virtual_attributes(admin: Api) -> None:
    user = admin.get("/types/user").json()
    assert user["supports_templates"] is True
    attrs = {
        a["name"]: a for tab in user["tabs"] for sec in tab["sections"] for a in sec["attributes"]
    }
    assert attrs["roles"]["stored"] is False  # memberships live on the role entries
    assert "stored" not in attrs["uid"]
    assert admin.get("/types/department").json()["supports_templates"] is False
