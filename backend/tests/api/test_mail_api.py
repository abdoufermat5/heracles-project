"""API v2 tests for the Mail plugin."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app

BASE = demo.BASE
ADMIN = demo.ADMIN_DN
ALIAS = f"ou=alias,{BASE}"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"


def q(dn: str) -> str:
    """URL-encode a DN for API paths."""
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


class MailDemoDirectory(MemoryDirectory):
    """MemoryDirectory that includes mail and alias schema objectClasses."""

    def schema_object_classes(self) -> set[str]:
        return super().schema_object_classes() | {
            "gosamailaccount",
            "fdgroupmail",
            "mailaliasdistribution",
            "mailaliasredirection",
        }


def build_mail_demo_app() -> FastAPI:
    """Build a demo FastAPI application with mail schema objectClasses and alias container."""
    directory = demo.build_demo_directory()
    directory.__class__ = MailDemoDirectory
    directory.add(
        ALIAS,
        {"objectClass": [b"organizationalUnit"], "ou": [b"alias"]},
    )
    settings = ApiSettings(
        admin_dns=[demo.ADMIN_DN],
        directory_labels={"main": "Demo directory"},
    )
    settings.session.cookie_secure = False
    return create_full_app(settings, {"main": directory})


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    with TestClient(build_mail_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str = "admin") -> Api:
    return Api(app_client).login(user)


def test_mail_plugin_registers_alias_types(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    assert "mail_alias_distribution" in types
    assert "mail_alias_redirection" in types
    assert types["mail_alias_distribution"]["can_create"] is True
    assert types["mail_alias_redirection"]["can_create"] is True


def test_user_type_descriptor_has_mail_tab(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    desc = a.get("/types/user").json()
    tabs = {t["name"]: t for t in desc["tabs"]}
    assert "mail" in tabs
    mail_tab = tabs["mail"]
    assert mail_tab["optional"] is True
    attrs = {a_desc["name"] for sec in mail_tab["sections"] for a_desc in sec["attributes"]}
    assert {
        "mail",
        "gosaMailServer",
        "gosaMailQuota",
        "gosaMailAlternateAddress",
        "gosaMailForwardingAddress",
        "flag_vacation",
        "flag_localonly",
        "flag_ownmailbox",
        "gosaVacationStart",
        "gosaVacationStop",
        "gosaVacationMessage",
    } <= attrs


def test_patch_user_mail_account(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    user_dn = f"uid=jdoe,ou=people,{BASE}"

    # Activate mail tab on jdoe
    patch_body = {
        "tabs": {
            "mail": {
                "active": True,
                "values": {
                    "mail": "jdoe@heracles.test",
                    "gosaMailServer": "mail.heracles.test",
                    "gosaMailQuota": 512,
                    "gosaMailAlternateAddress": ["john.doe@heracles.test"],
                    "gosaMailForwardingAddress": ["jdoe.personal@example.com"],
                    "flag_localonly": True,
                    "flag_vacation": True,
                    "gosaVacationStart": "2026-11-10",
                    "gosaVacationStop": "2026-11-20",
                    "gosaVacationMessage": "Away on business",
                },
            }
        }
    }
    r = a.patch(f"/objects/user/{q(user_dn)}", patch_body)
    assert r.status_code == 200, r.text
    state = r.json()
    mail_tab = state["tabs"]["mail"]
    assert mail_tab["active"] is True
    assert mail_tab["values"]["mail"] == "jdoe@heracles.test"
    assert mail_tab["values"]["gosaMailServer"] == "mail.heracles.test"
    assert mail_tab["values"]["gosaMailQuota"] == 512
    assert mail_tab["values"]["flag_localonly"] is True
    assert mail_tab["values"]["flag_vacation"] is True
    assert mail_tab["values"]["flag_ownmailbox"] is False
    assert mail_tab["values"]["gosaVacationStart"] == "2026-11-10"
    assert mail_tab["values"]["gosaVacationStop"] == "2026-11-20"
    assert mail_tab["values"]["gosaVacationMessage"] == "Away on business"

    # GET confirms persistence
    get_res = a.get(f"/objects/user/{q(user_dn)}").json()
    assert get_res["tabs"]["mail"]["values"]["gosaMailQuota"] == 512


def test_patch_user_mail_turn_off_vacation(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    user_dn = f"uid=jdoe,ou=people,{BASE}"

    # Setup vacation first
    a.patch(
        f"/objects/user/{q(user_dn)}",
        {
            "tabs": {
                "mail": {
                    "active": True,
                    "values": {
                        "mail": "jdoe@heracles.test",
                        "flag_vacation": True,
                        "gosaVacationStart": "2026-11-10",
                        "gosaVacationStop": "2026-11-20",
                        "gosaVacationMessage": "Away",
                    },
                }
            }
        },
    )

    # Now turn off vacation
    r = a.patch(
        f"/objects/user/{q(user_dn)}",
        {
            "tabs": {
                "mail": {
                    "values": {
                        "flag_vacation": False,
                    }
                }
            }
        },
    )
    assert r.status_code == 200, r.text
    mail_vals = r.json()["tabs"]["mail"]["values"]
    assert mail_vals["flag_vacation"] is False
    assert mail_vals["gosaVacationStart"] is None
    assert mail_vals["gosaVacationStop"] is None
    assert mail_vals["gosaVacationMessage"] is None


def test_patch_user_mail_uniqueness_validation(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    user1_dn = f"uid=jdoe,ou=people,{BASE}"
    user2_dn = f"uid=asmith,ou=people,ou=paris,{BASE}"

    # Activate mail on user1
    a.patch(
        f"/objects/user/{q(user1_dn)}",
        {
            "tabs": {
                "mail": {
                    "active": True,
                    "values": {
                        "mail": "primary@heracles.test",
                        "gosaMailAlternateAddress": ["alias1@heracles.test"],
                    },
                }
            }
        },
    )

    # Attempt to use same mail on user2
    r1 = a.patch(
        f"/objects/user/{q(user2_dn)}",
        {
            "tabs": {
                "mail": {
                    "active": True,
                    "values": {
                        "mail": "primary@heracles.test",
                    },
                }
            }
        },
    )
    assert r1.status_code == 422
    err1 = r1.json()["error"]
    assert err1["code"] == "validation"
    assert "mail.mail" in err1["fields"]

    # Attempt to use alias1 as mail on user2
    r2 = a.patch(
        f"/objects/user/{q(user2_dn)}",
        {
            "tabs": {
                "mail": {
                    "active": True,
                    "values": {
                        "mail": "alias1@heracles.test",
                    },
                }
            }
        },
    )
    assert r2.status_code == 422
    assert "mail.mail" in r2.json()["error"]["fields"]


def test_alias_distribution_crud_api(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # Create
    create_body = {
        "base": BASE,
        "tabs": {
            "main": {
                "values": {
                    "cn": "api-dist",
                    "description": "API distribution list",
                    "mail": "api-dist@heracles.test",
                    "gosaMailAlternateAddress": ["api-alias@heracles.test"],
                    "gosaMailServer": "mail.heracles.test",
                    "aliasExpirationDate": "2027-06-30",
                }
            }
        },
    }
    r = a.post("/objects/mail_alias_distribution", create_body)
    assert r.status_code == 201, r.text
    created = r.json()
    dn = created["dn"]
    assert dn.startswith("cn=api-dist,")

    # GET
    get_res = a.get(f"/objects/mail_alias_distribution/{q(dn)}")
    assert get_res.status_code == 200
    vals = get_res.json()["tabs"]["main"]["values"]
    assert vals["cn"] == "api-dist"
    assert vals["mail"] == "api-dist@heracles.test"
    assert vals["aliasExpirationDate"] == "2027-06-30"

    # PATCH
    patch_res = a.patch(
        f"/objects/mail_alias_distribution/{q(dn)}",
        {"tabs": {"main": {"values": {"description": "Updated distribution"}}}},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["tabs"]["main"]["values"]["description"] == "Updated distribution"

    # DELETE
    del_res = a.delete(f"/objects/mail_alias_distribution/{q(dn)}")
    assert del_res.status_code == 204
    assert a.get(f"/objects/mail_alias_distribution/{q(dn)}").status_code == 404


def test_alias_redirection_crud_api(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # Missing forwarding address -> validation error
    r_bad = a.post(
        "/objects/mail_alias_redirection",
        {
            "base": BASE,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "api-redir-bad",
                        "mail": "bad-redir@heracles.test",
                        "gosaMailForwardingAddress": [],
                    }
                }
            },
        },
    )
    assert r_bad.status_code == 422
    assert "main.gosaMailForwardingAddress" in r_bad.json()["error"]["fields"]

    # Valid create
    r = a.post(
        "/objects/mail_alias_redirection",
        {
            "base": BASE,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "api-redir",
                        "description": "API redirection list",
                        "mail": "api-redir@heracles.test",
                        "gosaMailForwardingAddress": ["target-api@example.com"],
                        "aliasExpirationDate": "2027-12-31",
                    }
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]

    # GET
    res = a.get(f"/objects/mail_alias_redirection/{q(dn)}")
    assert res.status_code == 200
    vals = res.json()["tabs"]["main"]["values"]
    assert vals["mail"] == "api-redir@heracles.test"
    assert vals["gosaMailForwardingAddress"] == ["target-api@example.com"]

    # DELETE
    assert a.delete(f"/objects/mail_alias_redirection/{q(dn)}").status_code == 204
