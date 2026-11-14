"""End-to-end tests against the real container stack (OpenLDAP + Heracles).

    make e2e        # builds and starts the stack, runs these tests

Skipped unless ``HERACLES_E2E_URL`` is set (e.g. ``http://localhost:8420``).
Every object is created inside a fresh department and removed at the end.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import httpx2
import pytest

URL = os.environ.get("HERACLES_E2E_URL", "")
BASE = "dc=heracles,dc=test"
ADMIN = ("alice", "alice-secret")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="set HERACLES_E2E_URL to run the end-to-end tests"),
]


def q(dn: str) -> str:
    return quote(dn, safe="")


class Client:
    """Browser-like API client: cookies, CSRF header, JSON."""

    def __init__(self) -> None:
        self.http = httpx2.Client(base_url=URL, timeout=20)
        self.csrf = ""

    def refresh_csrf(self) -> None:
        self.csrf = self.http.get("/api/v2/auth/csrf").json()["token"]

    def login(self, username: str, password: str) -> httpx2.Response:
        self.refresh_csrf()
        r = self.post(
            "/auth/login", {"directory": "main", "username": username, "password": password}
        )
        self.refresh_csrf()
        return r

    def get(self, path: str, **params: Any) -> httpx2.Response:
        return self.http.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> httpx2.Response:
        return self.http.post(f"/api/v2{path}", json=body, headers={"X-CSRF-Token": self.csrf})

    def patch(self, path: str, body: Any) -> httpx2.Response:
        return self.http.patch(f"/api/v2{path}", json=body, headers={"X-CSRF-Token": self.csrf})

    def delete(self, path: str) -> httpx2.Response:
        return self.http.delete(f"/api/v2{path}", headers={"X-CSRF-Token": self.csrf})


def ok(r: httpx2.Response, status: int = 200) -> Any:
    assert r.status_code == status, f"{r.request.method} {r.request.url}: {r.status_code} {r.text}"
    return r.json() if r.content else None


@pytest.fixture(scope="module")
def admin() -> Client:
    c = Client()
    ok(c.login(*ADMIN))
    return c


@pytest.fixture(scope="module")
def dept(admin: Client) -> Iterator[str]:
    """A throw-away department; everything created below it is deleted afterwards."""
    name = f"e2e-{secrets.token_hex(3)}"
    created = ok(
        admin.post(
            "/objects/department",
            {"base": BASE, "tabs": {"main": {"values": {"ou": name, "description": "E2E run"}}}},
        ),
        201,
    )
    dn = created["dn"]
    yield dn
    # cleanup: delete children deepest first, then the department
    for type_name in ("dns_zone", "server", "sudo", "user", "posix_group", "group"):
        page = admin.get(f"/objects/{type_name}", base=dn, scope="sub", limit=500)
        if page.status_code != 200:
            continue
        for item in sorted(page.json()["items"], key=lambda i: -i["dn"].count(",")):
            admin.delete(f"/objects/{type_name}/{q(item['dn'])}")
    r = admin.delete(f"/objects/department/{q(dn)}")
    assert r.status_code == 204, f"department cleanup failed: {r.status_code} {r.text}"


# --------------------------------------------------------------------------- basics


def test_ready_and_spa_served() -> None:
    r = httpx2.get(f"{URL}/readyz", timeout=10)
    assert r.json() == {"status": "ok", "directories": {"main": True}}
    page = httpx2.get(f"{URL}/types/user", timeout=10)  # SPA history fallback
    assert page.status_code == 200 and "<title>Heracles" in page.text


def test_login_rejects_bad_password() -> None:
    c = Client()
    r = c.login("alice", "wrong-password")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_types_follow_the_loaded_schema(admin: Client) -> None:
    names = {t["name"] for t in ok(admin.get("/types"))}
    # schemas loaded in the test server: core, nis, sudo, ssh, dns, dhcp, systems, smb,
    # mail, ftp
    assert {"user", "group", "department", "posix_group", "sudo", "dns_zone", "server"} <= names
    assert "dhcp_configuration" in names
    # not loaded (no ipam schema in the test server)
    assert "ipam_subnet" not in names
    user_tabs = {t["name"] for t in ok(admin.get("/types/user"))["tabs"]}
    assert {"main", "posix", "ssh", "smb", "ftp_accounts", "mail"} <= user_tabs


# ---------------------------------------------------------------- users end to end


def test_user_lifecycle_on_real_ldap(admin: Client, dept: str) -> None:
    key = (
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEN4afpmpx6UcN3RZPI3PaZEelen0CCXeFfX96TNN8Fw e2e@host"
    )
    created = ok(
        admin.post(
            "/objects/user",
            {
                "base": dept,
                "tabs": {
                    "main": {
                        "values": {
                            "uid": "e2e-jdoe",
                            "givenName": "Jérôme",
                            "sn": "Doe",
                            "mail": "e2e-jdoe@heracles.test",
                            "userPassword": "first-secret-123",
                        }
                    },
                    "posix": {"active": True, "values": {}},
                    "ssh": {"active": True, "values": {"sshPublicKey": [key]}},
                },
            },
        ),
        201,
    )
    dn = created["dn"]
    assert dn == f"uid=e2e-jdoe,ou=people,{dept}"

    obj = ok(admin.get(f"/objects/user/{q(dn)}"))
    posix = obj["tabs"]["posix"]["values"]
    assert posix["homeDirectory"] == "/home/e2e-jdoe"
    assert posix["uidNumber"] >= 1101 and posix["gidNumber"] >= 1101
    assert obj["tabs"]["main"]["values"]["cn"] == "Jérôme Doe"
    assert obj["tabs"]["ssh"]["active"] is True

    # the personal POSIX group was created next to the user's department
    groups = ok(admin.get("/objects/posix_group", base=dept, scope="sub"))["items"]
    assert [g["values"]["cn"] for g in groups] == ["e2e-jdoe"]

    # the new user can log in with the password hashed by Heracles and checked by slapd
    user = Client()
    ok(user.login("e2e-jdoe", "first-secret-123"))
    me = ok(user.get("/auth/me"))
    assert me["dn"] == dn

    # edit lock: taken by the admin, a second session gets 409 on PATCH
    ok(admin.post(f"/objects/user/{q(dn)}/lock"))
    r = user.patch(f"/objects/user/{q(dn)}", {"tabs": {"main": {"values": {"sn": "X"}}}})
    assert r.status_code in (403, 409)
    ok(admin.patch(f"/objects/user/{q(dn)}", {"tabs": {"main": {"values": {"sn": "Dupont"}}}}))
    assert admin.delete(f"/objects/user/{q(dn)}/lock").status_code == 204
    assert (
        ok(admin.get(f"/objects/user/{q(dn)}"))["tabs"]["main"]["values"]["cn"] == "Jérôme Dupont"
    )

    # password change, then login with the new one
    ok(
        admin.patch(
            f"/objects/user/{q(dn)}",
            {"tabs": {"main": {"values": {"userPassword": "second-secret-456"}}}},
        )
    )
    assert Client().login("e2e-jdoe", "first-secret-123").status_code == 401
    ok(Client().login("e2e-jdoe", "second-secret-456"))

    # account lock: password and SSH keys disabled, login refused; unlock restores
    assert ok(admin.post(f"/users/{q(dn)}/lock"))["locked"] is True
    keys = ok(admin.get(f"/objects/user/{q(dn)}"))["tabs"]["ssh"]["values"]["sshPublicKey"]
    assert keys[0].startswith("disabled-ssh-ed25519")
    assert Client().login("e2e-jdoe", "second-secret-456").status_code == 401
    assert ok(admin.post(f"/users/{q(dn)}/unlock"))["locked"] is False
    ok(Client().login("e2e-jdoe", "second-secret-456"))

    # snapshot then restore
    snap = ok(admin.post(f"/objects/user/{q(dn)}/snapshots", {"description": "e2e"}), 201)
    ok(admin.patch(f"/objects/user/{q(dn)}", {"tabs": {"main": {"values": {"sn": "Changed"}}}}))
    ok(admin.post(f"/snapshots/{q(snap['id'])}/restore"))
    assert ok(admin.get(f"/objects/user/{q(dn)}"))["tabs"]["main"]["values"]["sn"] == "Dupont"
    assert admin.delete(f"/snapshots/{q(snap['id'])}").status_code == 204

    # validation error comes back as 422 with the field key
    r = admin.patch(
        f"/objects/user/{q(dn)}", {"tabs": {"main": {"values": {"userPassword": "abc"}}}}
    )
    assert r.status_code == 422 and "main.userPassword" in r.json()["error"]["fields"]

    # deleting the user removes its personal group
    assert admin.delete(f"/objects/user/{q(dn)}").status_code == 204
    assert ok(admin.get("/objects/posix_group", base=dept, scope="sub"))["items"] == []


def test_listing_search_and_paging(admin: Client) -> None:
    page = ok(admin.get("/objects/user", base=BASE, scope="sub", q="alice"))
    assert [i["values"]["uid"] for i in page["items"]] == ["alice"]
    first = ok(admin.get("/objects/user", base=BASE, scope="sub", limit=1))
    assert len(first["items"]) == 1 and first["next_cursor"]


# --------------------------------------------------------------- other object types


def test_sudo_role(admin: Client, dept: str) -> None:
    dn = ok(
        admin.post(
            "/objects/sudo",
            {
                "base": dept,
                "tabs": {
                    "main": {
                        "values": {
                            "cn": "e2e-admins",
                            "sudoUser": ["%wheel", "bob"],
                            "sudoCommand": ["/usr/bin/systemctl restart nginx"],
                        }
                    },
                    "options": {
                        "values": {"sudoOption": ["!authenticate", "env_keep+=SSH_AUTH_SOCK"]}
                    },
                },
            },
        ),
        201,
    )["dn"]
    role = ok(admin.get(f"/objects/sudo/{q(dn)}"))["tabs"]
    assert role["main"]["values"]["sudoHost"] == ["ALL"]
    r = admin.patch(
        f"/objects/sudo/{q(dn)}", {"tabs": {"options": {"values": {"sudoOption": ["nope"]}}}}
    )
    assert r.status_code == 422


def test_dns_zone_with_records_and_reverse(admin: Client, dept: str) -> None:
    dn = ok(
        admin.post(
            "/objects/dns_zone",
            {
                "base": dept,
                "tabs": {
                    "main": {
                        "values": {
                            "zoneName": "e2e.test",
                            "soaPrimary": "ns1.e2e.test",
                            "soaMail": "hostmaster@e2e.test",
                            "reverseZones": ["0.10.10.in-addr.arpa"],
                            "dnsRecord": [
                                {"name": "@", "type": "NS", "value": "ns1.e2e.test."},
                                {"name": "ns1", "type": "A", "value": "10.10.0.2"},
                                {"name": "www", "type": "A", "value": "10.10.0.80"},
                            ],
                        }
                    }
                },
            },
        ),
        201,
    )["dn"]
    zone = ok(admin.get(f"/objects/dns_zone/{q(dn)}"))["tabs"]["main"]["values"]
    names = sorted(r["name"] for r in zone["dnsRecord"])
    assert names == ["@", "ns1", "www"]
    assert str(zone["soaSerial"]).isdigit()
    bad = admin.patch(
        f"/objects/dns_zone/{q(dn)}",
        {
            "tabs": {
                "main": {
                    "values": {"dnsRecord": [{"name": "x", "type": "A", "value": "999.1.1.1"}]}
                }
            }
        },
    )
    assert bad.status_code == 422


def test_server_with_interface(admin: Client, dept: str) -> None:
    dn = ok(
        admin.post(
            "/objects/server",
            {
                "base": dept,
                "tabs": {
                    "main": {
                        "values": {
                            "cn": "e2e-srv",
                            "description": "E2E server",
                            "networkInterfaces": [
                                {
                                    "cn": "eth0",
                                    "macAddress": "52:54:00:AA:BB:01",
                                    "ipHostNumber": ["10.10.0.50"],
                                }
                            ],
                        }
                    }
                },
            },
        ),
        201,
    )["dn"]
    values = ok(admin.get(f"/objects/server/{q(dn)}"))["tabs"]["main"]["values"]
    assert values["networkInterfaces"][0]["macAddress"] == "52:54:00:aa:bb:01"
    # the same MAC on another server is refused (directory-wide uniqueness)
    dup = admin.post(
        "/objects/server",
        {
            "base": dept,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "e2e-srv2",
                        "networkInterfaces": [{"cn": "eth0", "macAddress": "52:54:00:aa:bb:01"}],
                    }
                }
            },
        },
    )
    assert dup.status_code == 422


# ------------------------------------------------------------------ access control


def test_regular_user_cannot_administer(admin: Client, dept: str) -> None:
    bob = Client()
    ok(bob.login("bob", "bob-secret"))
    r = bob.post(
        "/objects/user",
        {
            "base": dept,
            "tabs": {"main": {"values": {"uid": "intruder", "givenName": "I", "sn": "I"}}},
        },
    )
    assert r.status_code == 403
    assert ok(bob.get("/types"))  # can still see the metadata
    assert bob.get(f"/objects/user/{q(f'uid=alice,ou=people,{BASE}')}").status_code == 403
