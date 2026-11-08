"""API v2 tests: copy, multiple edit, references, roles tab, deleted snapshots."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles.demo import BASE
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"
LYON = f"ou=lyon,{BASE}"
ASMITH = f"uid=asmith,ou=people,{PARIS}"
BMARTIN = f"uid=bmartin,ou=people,{PARIS}"
CDUPONT = f"uid=cdupont,ou=people,{LYON}"
DLEFEVRE = f"uid=dlefevre,ou=people,{LYON}"
MANAGERS = f"cn=lyon-managers,ou=roles,{LYON}"
LYON_STAFF = f"cn=lyon-staff,ou=groups,{LYON}"


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


# ----------------------------------------------------------------------- copy


def test_copy_clears_unique_attributes(admin: Api) -> None:
    r = admin.post(f"/objects/user/{q(CDUPONT)}/copy", {"base": PARIS})
    assert r.status_code == 422
    assert "main.uid" in r.json()["error"]["fields"]

    r = admin.post(
        f"/objects/user/{q(CDUPONT)}/copy",
        {"base": PARIS, "values": {"main": {"uid": "cdupont2"}}},
    )
    assert r.status_code == 201, r.text
    new_dn = r.json()["dn"]
    assert new_dn == f"uid=cdupont2,ou=people,{PARIS}"
    copy = admin.get(f"/objects/user/{q(new_dn)}").json()["tabs"]["main"]["values"]
    source = admin.get(f"/objects/user/{q(CDUPONT)}").json()["tabs"]["main"]["values"]
    assert copy["sn"] == source["sn"]
    assert copy["givenName"] == source["givenName"]
    assert copy.get("mail") is None  # unique: cleared
    assert copy["cn"] == source["cn"]
    assert admin.get(f"/objects/user/{q(CDUPONT)}").status_code == 200  # source untouched


def test_copy_group_keeps_members_and_checks_acl(app_client: TestClient, admin: Api) -> None:
    r = admin.post(
        f"/objects/group/{q(LYON_STAFF)}/copy",
        {"base": PARIS, "values": {"main": {"cn": "paris-staff"}}},
    )
    assert r.status_code == 201, r.text
    body = admin.get(f"/objects/group/{q(r.json()['dn'])}").json()
    assert sorted(body["tabs"]["main"]["values"]["member"]) == sorted([CDUPONT, DLEFEVRE])

    user = Api(app_client).login("bmartin")
    denied = user.post(
        f"/objects/group/{q(LYON_STAFF)}/copy",
        {"base": PARIS, "values": {"main": {"cn": "nope"}}},
    )
    assert denied.status_code == 403
    assert (
        admin.post(f"/objects/group/{q('cn=x,dc=nope')}/copy", {"base": PARIS}).status_code == 404
    )


# ----------------------------------------------------------------- bulk edit


def test_bulk_edit_ops(admin: Api) -> None:
    dns = [CDUPONT, DLEFEVRE]
    r = admin.patch(
        "/objects/user/_bulk",
        {"dns": dns, "changes": {"main": {"employeeType": {"op": "set", "value": "contractor"}}}},
    )
    assert r.status_code == 200, r.text
    assert [x["ok"] for x in r.json()["results"]] == [True, True]
    for dn in dns:
        values = admin.get(f"/objects/user/{q(dn)}").json()["tabs"]["main"]["values"]
        assert values["employeeType"] == "contractor"

    r = admin.patch(
        "/objects/user/_bulk",
        {"dns": dns, "changes": {"main": {"employeeType": {"op": "clear"}}}},
    )
    assert all(x["ok"] for x in r.json()["results"])
    values = admin.get(f"/objects/user/{q(CDUPONT)}").json()["tabs"]["main"]["values"]
    assert values.get("employeeType") is None


def test_bulk_edit_list_add_remove(admin: Api) -> None:
    groups = [LYON_STAFF, f"cn=admins,ou=groups,{BASE}"]
    r = admin.patch(
        "/objects/group/_bulk",
        {"dns": groups, "changes": {"main": {"member": {"op": "add", "value": [ASMITH]}}}},
    )
    assert all(x["ok"] for x in r.json()["results"]), r.text
    for dn in groups:
        members = admin.get(f"/objects/group/{q(dn)}").json()["tabs"]["main"]["values"]["member"]
        assert ASMITH in members
    r = admin.patch(
        "/objects/group/_bulk",
        {"dns": groups, "changes": {"main": {"member": {"op": "remove", "value": [ASMITH]}}}},
    )
    assert all(x["ok"] for x in r.json()["results"])
    members = admin.get(f"/objects/group/{q(LYON_STAFF)}").json()["tabs"]["main"]["values"][
        "member"
    ]
    assert ASMITH not in members


def test_bulk_edit_partial_failures(app_client: TestClient, admin: Api) -> None:
    dns = [CDUPONT, f"uid=ghost,ou=people,{LYON}", DLEFEVRE]
    r = admin.patch(
        "/objects/user/_bulk",
        {"dns": dns, "changes": {"main": {"sn": {"op": "clear"}}}},
    )
    results = r.json()["results"]
    assert [x["ok"] for x in results] == [False, False, False]
    assert results[0]["code"] == "validation" and "main.sn" in results[0]["fields"]
    assert results[1]["code"] == "not_found"

    r = admin.patch(
        "/objects/user/_bulk",
        {"dns": dns, "changes": {"main": {"l": {"op": "set", "value": "Lyon"}}}},
    )
    assert [x["ok"] for x in r.json()["results"]] == [True, False, True]

    bad = admin.patch(
        "/objects/user/_bulk",
        {"dns": [CDUPONT], "changes": {"main": {"uid": {"op": "bogus"}}}},
    )
    assert bad.json()["results"][0]["code"] == "validation"

    user = Api(app_client).login("bmartin")
    denied = user.patch(
        "/objects/user/_bulk",
        {"dns": [CDUPONT], "changes": {"main": {"l": {"op": "set", "value": "x"}}}},
    )
    assert denied.json()["results"][0]["code"] == "forbidden"


def test_bulk_editable_attributes(admin: Api) -> None:
    r = admin.post("/objects/user/_bulk/attributes", {"dns": [CDUPONT, DLEFEVRE]})
    assert r.status_code == 200, r.text
    attrs = r.json()["attributes"]
    assert "employeeType" in attrs["main"]
    assert "userPassword" not in attrs["main"]
    assert "jpegPhoto" not in attrs["main"]
    assert "cn" not in attrs["main"]


# ----------------------------------------------------------------- references


def test_references(admin: Api, app_client: TestClient) -> None:
    refs = admin.get(f"/objects/user/{q(CDUPONT)}/references").json()
    pairs = {(r["type"], r["label"], r["attribute"]) for r in refs}
    assert ("group", "lyon-staff", "member") in pairs
    assert ("role", "lyon-managers", "roleOccupant") in pairs
    assert all("templates" not in r["dn"] for r in refs)

    # the Lyon department carries an ACL assignment naming the Lyon managers role
    refs = admin.get(f"/objects/role/{q(MANAGERS)}/references").json()
    assert any(r["attribute"] == "acl_assignment" and r["type"] == "department" for r in refs)

    # self-service user: cannot read the other object's references
    user = Api(app_client).login("bmartin")
    assert user.get(f"/objects/user/{q(CDUPONT)}/references").status_code == 403
    own = user.get(f"/objects/user/{q(BMARTIN)}/references")
    assert own.status_code == 200
    assert own.json() == []


def test_references_hide_unreadable_objects(app_client: TestClient, admin: Api) -> None:
    helpdesk = Api(app_client).login("helpdesk")
    refs = helpdesk.get(f"/objects/user/{q(CDUPONT)}/references")
    assert refs.status_code == 200
    # helpdesk can read users and departments only: groups and roles are hidden
    assert refs.json() == []


# --------------------------------------------------------------------- roles


def test_roles_tab_reads_and_writes_role_entries(admin: Api) -> None:
    body = admin.get(f"/objects/user/{q(CDUPONT)}").json()
    assert body["tabs"]["roles"]["values"]["roles"] == [MANAGERS]
    assert body["acl"]["roles"]["attributes"]["roles"].startswith("rw")

    r = admin.patch(
        f"/objects/user/{q(DLEFEVRE)}", {"tabs": {"roles": {"values": {"roles": [MANAGERS]}}}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["tabs"]["roles"]["values"]["roles"] == [MANAGERS]
    role = admin.get(f"/objects/role/{q(MANAGERS)}").json()
    assert sorted(role["tabs"]["main"]["values"]["roleOccupant"]) == sorted([CDUPONT, DLEFEVRE])

    r = admin.patch(f"/objects/user/{q(CDUPONT)}", {"tabs": {"roles": {"values": {"roles": None}}}})
    assert r.status_code == 200, r.text
    role = admin.get(f"/objects/role/{q(MANAGERS)}").json()
    assert role["tabs"]["main"]["values"]["roleOccupant"] == [DLEFEVRE]


def test_roles_tab_validates_targets(admin: Api) -> None:
    r = admin.patch(
        f"/objects/user/{q(DLEFEVRE)}",
        {"tabs": {"roles": {"values": {"roles": [LYON_STAFF]}}}},
    )
    assert r.status_code == 422
    assert "roles.roles" in r.json()["error"]["fields"]


def test_roles_tab_needs_write_on_the_role(app_client: TestClient) -> None:
    # Lyon managers may edit users in Lyon but only read roles
    manager = Api(app_client).login("cdupont")
    r = manager.patch(
        f"/objects/user/{q(DLEFEVRE)}", {"tabs": {"roles": {"values": {"roles": [MANAGERS]}}}}
    )
    assert r.status_code == 422, r.text
    assert "roles.roles" in r.json()["error"]["fields"]


# ----------------------------------------------------------- deleted snapshots


def test_deleted_snapshots_listing_and_restore(admin: Api) -> None:
    target = DLEFEVRE
    assert (
        admin.post(f"/objects/user/{q(target)}/snapshots", {"description": "before"}).status_code
        == 201
    )
    assert admin.get("/snapshots/deleted").json() == []
    assert admin.delete(f"/objects/user/{q(target)}").status_code == 204

    deleted = admin.get("/snapshots/deleted", type="user").json()
    assert [d["object_dn"] for d in deleted] == [target]
    assert admin.get("/snapshots/deleted", type="group").json() == []
    assert admin.get("/snapshots/deleted", base=PARIS).json() == []

    r = admin.post(f"/snapshots/{q(deleted[0]['id'])}/restore")
    assert r.status_code == 200, r.text
    assert admin.get(f"/objects/user/{q(target)}").status_code == 200
    assert admin.get("/snapshots/deleted").json() == []
