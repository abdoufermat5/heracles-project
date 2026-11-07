"""API v2 integration tests for personal plugin tabs on users."""

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
ASMITH = f"uid=asmith,ou=people,{PARIS}"


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
def app_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    orig_builder = demo.build_demo_directory

    def _build_demo_dir() -> MemoryDirectory:
        d = orig_builder()
        d.set_schema_object_classes(d.schema_object_classes() | {"fdpersonalinfo"})
        return d

    monkeypatch.setattr(demo, "build_demo_directory", _build_demo_dir)
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_user_descriptor_includes_personal_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "personal" in tabs

    tab = tabs["personal"]
    assert tab["label"] == "Personal"
    assert tab["optional"] is True

    sections = {s["name"]: s for s in tab["sections"]}
    assert "personal_info" in sections
    assert "contact" in sections

    p_attrs = {attr["name"]: attr for attr in sections["personal_info"]["attributes"]}
    assert "personalTitle" in p_attrs
    assert "fdNickName" in p_attrs
    assert "fdBadge" in p_attrs
    assert "dateOfBirth" in p_attrs
    assert "gender" in p_attrs
    assert "co" in p_attrs
    assert "fdContractStartDate" in p_attrs
    assert "fdContractEndDate" in p_attrs
    assert "fdPhotoVisible" in p_attrs

    c_attrs = {attr["name"]: attr for attr in sections["contact"]["attributes"]}
    assert "fdSocialAccount" in c_attrs
    assert "fdPrivateMail" in c_attrs
    assert "socialUrls" in c_attrs


def test_admin_patch_activate_and_read_personal_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # Initial check: personal tab inactive on asmith
    obj = a.get(f"/objects/user/{q(ASMITH)}").json()
    assert obj["tabs"]["personal"]["active"] is False

    # PATCH activating personal tab with values
    patch_payload = {
        "tabs": {
            "personal": {
                "active": True,
                "values": {
                    "personalTitle": "Dr.",
                    "fdNickName": "Alice",
                    "fdBadge": "BADGE-1234",
                    "dateOfBirth": "1990-03-25",
                    "gender": "F",
                    "co": "United Kingdom",
                    "fdContractStartDate": "2023-01-01",
                    "fdContractEndDate": "2027-12-31",
                    "fdPhotoVisible": True,
                    "fdPrivateMail": ["alice@private.example.org"],
                    "fdSocialAccount": [
                        {"site": "github", "id": "alicesmith"},
                        {"site": "matrix", "id": "@alice:matrix.org"},
                    ],
                },
            }
        }
    }
    r = a.patch(f"/objects/user/{q(ASMITH)}", patch_payload)
    assert r.status_code == 200, r.text
    res = r.json()
    ptab = res["tabs"]["personal"]
    assert ptab["active"] is True
    assert ptab["values"]["personalTitle"] == "Dr."
    assert ptab["values"]["fdNickName"] == "Alice"
    assert ptab["values"]["fdBadge"] == "BADGE-1234"
    assert ptab["values"]["dateOfBirth"] == "1990-03-25"
    assert ptab["values"]["gender"] == "F"
    assert ptab["values"]["co"] == "United Kingdom"
    assert ptab["values"]["fdContractStartDate"] == "2023-01-01"
    assert ptab["values"]["fdContractEndDate"] == "2027-12-31"
    assert ptab["values"]["fdPhotoVisible"] is True
    assert ptab["values"]["fdPrivateMail"] == ["alice@private.example.org"]
    assert ptab["values"]["fdSocialAccount"] == [
        {"site": "github", "id": "alicesmith"},
        {"site": "matrix", "id": "@alice:matrix.org"},
    ]
    assert (
        ptab["values"]["socialUrls"]
        == "https://github.com/alicesmith\nhttps://matrix.to/#/@alice:matrix.org"
    )

    # Subsequent GET verifies persistence
    obj = a.get(f"/objects/user/{q(ASMITH)}").json()
    ptab = obj["tabs"]["personal"]
    assert ptab["active"] is True
    assert ptab["values"]["personalTitle"] == "Dr."
    assert ptab["values"]["fdBadge"] == "BADGE-1234"
    assert (
        ptab["values"]["socialUrls"]
        == "https://github.com/alicesmith\nhttps://matrix.to/#/@alice:matrix.org"
    )


def test_admin_patch_update_values(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # Activate tab
    a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "active": True,
                    "values": {
                        "fdNickName": "Initial",
                        "fdPhotoVisible": True,
                    },
                }
            }
        },
    )

    # Update values
    r = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "values": {
                        "fdNickName": "Updated",
                        "fdPhotoVisible": False,
                        "fdSocialAccount": [{"site": "twitter", "id": "alicesmith"}],
                    }
                }
            }
        },
    )
    assert r.status_code == 200, r.text
    ptab = r.json()["tabs"]["personal"]
    assert ptab["values"]["fdNickName"] == "Updated"
    assert ptab["values"]["fdPhotoVisible"] is False
    assert ptab["values"]["fdSocialAccount"] == [{"site": "twitter", "id": "alicesmith"}]
    assert ptab["values"]["socialUrls"] == "https://twitter.com/alicesmith"


def test_admin_patch_validation_errors(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # 1. Contract end date before start date
    r1 = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "active": True,
                    "values": {
                        "fdContractStartDate": "2026-01-01",
                        "fdContractEndDate": "2025-01-01",
                    },
                }
            }
        },
    )
    assert r1.status_code == 422
    assert "personal.fdContractEndDate" in r1.json()["error"]["fields"]

    # 2. Date of birth in the future
    r2 = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "active": True,
                    "values": {
                        "dateOfBirth": "2099-01-01",
                    },
                }
            }
        },
    )
    assert r2.status_code == 422
    assert "personal.dateOfBirth" in r2.json()["error"]["fields"]

    # 3. Invalid social account (matrix missing @)
    r3 = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "active": True,
                    "values": {
                        "fdSocialAccount": [{"site": "matrix", "id": "no_at_server"}],
                    },
                }
            }
        },
    )
    assert r3.status_code == 422
    assert "personal.fdSocialAccount" in r3.json()["error"]["fields"]

    # 4. Invalid private mail
    r4 = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "active": True,
                    "values": {
                        "fdPrivateMail": ["not-an-email"],
                    },
                }
            }
        },
    )
    assert r4.status_code == 422
    assert "personal.fdPrivateMail" in r4.json()["error"]["fields"]


def test_admin_patch_deactivate_personal_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # First activate
    a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "personal": {
                    "active": True,
                    "values": {"fdNickName": "AliceToDeactivate"},
                }
            }
        },
    )
    obj = a.get(f"/objects/user/{q(ASMITH)}").json()
    assert obj["tabs"]["personal"]["active"] is True

    # Then deactivate
    r = a.patch(f"/objects/user/{q(ASMITH)}", {"tabs": {"personal": {"active": False}}})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["tabs"]["personal"]["active"] is False

    # GET confirms inactive
    obj = a.get(f"/objects/user/{q(ASMITH)}").json()
    assert obj["tabs"]["personal"]["active"] is False
    assert obj["tabs"]["personal"]["values"] == {}


def test_create_user_with_personal_tab_via_api(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.post(
        "/objects/user",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "active": True,
                    "values": {
                        "uid": "newbie",
                        "givenName": "New",
                        "sn": "Bie",
                        "mail": "newbie@h.test",
                    },
                },
                "personal": {
                    "active": True,
                    "values": {
                        "personalTitle": "Ms.",
                        "fdNickName": "Newbie",
                        "dateOfBirth": "1998-12-05",
                        "gender": "F",
                        "fdSocialAccount": [{"site": "matrix", "id": "@newbie:example.com"}],
                    },
                },
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]
    assert dn == f"uid=newbie,ou=people,{PARIS}"

    obj = a.get(f"/objects/user/{q(dn)}").json()
    ptab = obj["tabs"]["personal"]
    assert ptab["active"] is True
    assert ptab["values"]["fdNickName"] == "Newbie"
    assert ptab["values"]["gender"] == "F"
    assert ptab["values"]["dateOfBirth"] == "1998-12-05"
    assert ptab["values"]["socialUrls"] == "https://matrix.to/#/@newbie:example.com"
