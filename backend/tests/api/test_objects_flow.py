"""End-to-end API v2 tests on the in-memory demo application."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles.api.state import AppState
from heracles.demo import BASE
from heracles.server import build_demo_app

PARIS = f"ou=paris,{BASE}"
LYON = f"ou=lyon,{BASE}"
ASMITH = f"uid=asmith,ou=people,{PARIS}"
CDUPONT = f"uid=cdupont,ou=people,{LYON}"
DLEFEVRE = f"uid=dlefevre,ou=people,{LYON}"


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
    with TestClient(build_demo_app()) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


def test_requires_authentication(app_client: TestClient) -> None:
    r = app_client.get("/api/v2/types")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_types_and_descriptor(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    assert {"user", "group", "role", "department"} <= types.keys()
    assert types["user"]["can_create"] is True
    desc = a.get("/types/user").json()
    assert desc["main_attr"] == "uid"
    assert desc["tabs"][0]["name"] == "main"
    assert a.get("/types/nope").status_code == 404


def test_types_expose_navigation_metadata(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    for t in types.values():
        assert t["nav"] in {"primary", "secondary", "hidden"}
        assert t["nav_group"]
    assert types["user"]["nav"] == "primary"
    assert types["user"]["nav_group"] == "people"
    assert types["user"]["count_key"] == "user"
    assert types["department"]["nav_group"] == "organization"
    assert types["department_o"]["nav"] == "hidden"
    desc = a.get("/types/user").json()
    assert (desc["nav"], desc["nav_group"], desc["count_key"]) == ("primary", "people", "user")


def test_tree_admin_sees_all_departments(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    [root] = a.get("/tree").json()
    assert root["dn"] == BASE
    labels = sorted(c["label"] for c in root["children"])
    assert labels == ["lyon", "paris"]


def test_listing_and_search(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    page = a.get("/objects/user", base=BASE, scope="sub", limit=3).json()
    assert page["total"] == 7
    assert len(page["items"]) == 3
    assert page["next_cursor"]
    assert "groups_count" in page["items"][0]
    # Test offset parameter for pagination
    page2 = a.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3).json()
    assert len(page2["items"]) == 3
    assert page2["items"][0]["dn"] != page["items"][0]["dn"]
    found = a.get("/objects/user", base=BASE, scope="sub", q="dupont").json()
    assert [i["dn"] for i in found["items"]] == [CDUPONT]


def test_listing_raw_filter(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    ok = a.get("/objects/user", base=BASE, scope="sub", filter="(&(uid=cdup*)(uid=*nt))")
    assert [i["dn"] for i in ok.json()["items"]] == [CDUPONT]
    assert ok.json()["total"] == 1
    bad = a.get("/objects/user", base=BASE, scope="sub", filter="(nosuchattr=1)")
    assert bad.status_code == 400
    assert "nosuchattr" in bad.json()["error"]["message"]
    # write-only attributes cannot be probed
    assert a.get("/objects/user", scope="sub", filter="(userPassword=*)").status_code == 400
    assert a.get("/objects/user", scope="sub", filter="(uid=").status_code == 400


def test_listing_round_trips_do_not_grow_with_the_page(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page of users costs the same number of directory operations whatever its size."""
    a = api(app_client, "admin")
    a.get("/types")  # resolves the ACLs of the session once
    state = cast(AppState, cast(FastAPI, app_client.app).state.heracles)
    directory = state.directories["main"]
    operations: list[str] = []
    for name in ("search", "get"):
        original = getattr(directory, name)

        def counted(*args: Any, _original: Any = original, _name: str = name, **kw: Any) -> Any:
            operations.append(_name)
            return _original(*args, **kw)

        monkeypatch.setattr(directory, name, counted)

    def cost(limit: int) -> int:
        operations.clear()
        page = a.get("/objects/user", base=BASE, scope="sub", limit=limit).json()
        assert len(page["items"]) == limit
        return len(operations)

    assert cost(1) == cost(7)


def count_searches(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the base DN of every directory search made from now on."""
    state = cast(AppState, cast(FastAPI, app_client.app).state.heracles)
    directory = state.directories["main"]
    original = directory.search
    searches: list[str] = []

    def counted(base: str, *args: Any, **kw: Any) -> Any:
        searches.append(base)
        return original(base, *args, **kw)

    monkeypatch.setattr(directory, "search", counted)
    return searches


def test_later_pages_reuse_the_first_page_snapshot(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = api(app_client, "admin")
    a.get("/types")  # resolves the ACLs of the session once
    searches = count_searches(app_client, monkeypatch)

    first = a.get("/objects/user", base=BASE, scope="sub", limit=3).json()
    first_cost = len(searches)
    searches.clear()
    second = a.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3).json()
    assert len(searches) < first_cost  # the listing search is not repeated
    assert second["total"] == first["total"] == 7
    assert len(second["items"]) == 3
    assert {i["dn"] for i in second["items"]}.isdisjoint(i["dn"] for i in first["items"])
    assert first["next_cursor"]

    # Reloading the first page searches again.
    searches.clear()
    a.get("/objects/user", base=BASE, scope="sub", limit=3)
    assert len(searches) == first_cost


def test_listing_snapshot_is_dropped_by_a_write(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = api(app_client, "admin")
    a.get("/types")
    searches = count_searches(app_client, monkeypatch)
    first = a.get("/objects/user", base=BASE, scope="sub", limit=3).json()
    first_cost = len(searches)
    assert first["total"] == 7

    r = a.post(
        "/objects/user",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "active": True,
                    "values": {"uid": "zed", "givenName": "Zed", "sn": "Last", "mail": "z@h.test"},
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    searches.clear()
    second = a.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3).json()
    assert second["total"] == 8
    assert len(searches) == first_cost  # the snapshot was dropped, so page 2 searched again


def test_listing_snapshot_is_dropped_by_any_non_read_request_even_a_failed_one(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = api(app_client, "admin")
    a.get("/types")
    searches = count_searches(app_client, monkeypatch)
    a.get("/objects/user", base=BASE, scope="sub", limit=3)
    first_cost = len(searches)

    # a POST refused before any object endpoint ran still drops the session's snapshots
    assert a.post("/objects/user", {}).status_code >= 400
    searches.clear()
    a.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3)
    assert len(searches) == first_cost

    # a GET does not
    a.get("/objects/user", base=BASE, scope="sub", limit=3)
    searches.clear()
    a.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3)
    assert len(searches) < first_cost

    # a write outside API v2 is recognised by the v1 session token header
    state = cast(AppState, cast(FastAPI, app_client.app).state.heracles)
    cookie = app_client.cookies[state.settings.session.cookie_name]
    with TestClient(app_client.app) as token_client:
        token_client.post("/api/v1/unknown", headers={"Session-Token": cookie})
    searches.clear()
    a.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3)
    assert len(searches) == first_cost


def test_account_lock_drops_the_listing_snapshot(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    a.get("/objects/user", base=BASE, scope="sub", limit=1, order="desc")
    assert a.post(f"/users/{q(ASMITH)}/lock").status_code == 200
    rest = a.get("/objects/user", base=BASE, scope="sub", limit=6, offset=1, order="desc").json()
    assert {i["dn"]: i["locked"] for i in rest["items"]}[ASMITH] is True


def test_listing_snapshots_are_not_shared_between_sessions(app_client: TestClient) -> None:
    admin = api(app_client, "admin")
    assert admin.get("/objects/user", base=BASE, scope="sub", limit=3).json()["total"] == 7
    with TestClient(app_client.app) as other_client:
        # a regular user sees (almost) nothing: admin's snapshot must not leak to it
        other = api(other_client, "bmartin")
        page = other.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3).json()
        assert page["total"] < 7
    with TestClient(app_client.app) as helpdesk_client:
        helpdesk = api(helpdesk_client, "helpdesk")
        page = helpdesk.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3).json()
        assert page["total"] == 7
    # and the admin's own snapshot is still served to the admin
    again = admin.get("/objects/user", base=BASE, scope="sub", limit=3, offset=3).json()
    assert again["total"] == 7


def test_crud_flow_with_lock(app_client: TestClient) -> None:
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
                        "mail": "n@h.test",
                    },
                }
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]
    assert dn == f"uid=newbie,ou=people,{PARIS}"

    obj = a.get(f"/objects/user/{q(dn)}").json()
    assert obj["tabs"]["main"]["values"]["cn"] == "New Bie"
    assert "w" in obj["acl"]["main"]["object"]

    assert a.post(f"/objects/user/{q(dn)}/lock").status_code == 200
    r = a.patch(f"/objects/user/{q(dn)}", {"tabs": {"main": {"values": {"sn": "Bee"}}}})
    assert r.status_code == 200, r.text
    assert r.json()["tabs"]["main"]["values"]["cn"] == "New Bee"
    assert a.delete(f"/objects/user/{q(dn)}/lock").status_code == 204

    assert a.delete(f"/objects/user/{q(dn)}").status_code == 204
    assert a.get(f"/objects/user/{q(dn)}").status_code == 404


def test_validation_error_format(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.post("/objects/user", {"base": PARIS, "tabs": {"main": {"values": {"uid": "x"}}}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation"
    assert "main.sn" in err["fields"]


def test_lock_conflict_between_users(app_client: TestClient) -> None:
    admin = api(app_client, "admin")
    assert admin.post(f"/objects/user/{q(DLEFEVRE)}/lock").status_code == 200
    with TestClient(app_client.app) as other_client:
        manager = api(other_client, "cdupont")
        r = manager.patch(
            f"/objects/user/{q(DLEFEVRE)}", {"tabs": {"main": {"values": {"sn": "X"}}}}
        )
        assert r.status_code == 409
        body = r.json()["error"]
        assert body["code"] == "locked"
        assert body["lock"]["user"].startswith("uid=admin")


def test_delegated_manager_is_scoped_to_lyon(app_client: TestClient) -> None:
    manager = api(app_client, "cdupont")  # occupant of the lyon-managers role
    # can edit a user in Lyon
    r = manager.patch(
        f"/objects/user/{q(DLEFEVRE)}", {"tabs": {"main": {"values": {"sn": "Lefebvre"}}}}
    )
    assert r.status_code == 200, r.text
    # cannot edit a user in Paris
    r = manager.patch(f"/objects/user/{q(ASMITH)}", {"tabs": {"main": {"values": {"sn": "Nope"}}}})
    assert r.status_code == 403
    # cannot create in Paris, can in Lyon
    types = {t["name"]: t for t in manager.get("/types").json()}
    assert types["user"]["can_create"] is False  # not at the base
    body = {"base": PARIS, "tabs": {"main": {"values": {"uid": "zz", "givenName": "Z", "sn": "Z"}}}}
    assert manager.post("/objects/user", body).status_code == 403
    body["base"] = LYON
    assert manager.post("/objects/user", body).status_code == 201


def test_self_service_only_on_own_entry(app_client: TestClient) -> None:
    me = api(app_client, "asmith")
    own = me.get(f"/objects/user/{q(ASMITH)}").json()
    assert own["acl"]["main"]["attributes"]["telephoneNumber"] == "rw"
    assert own["acl"]["main"]["attributes"]["sn"] == "r"
    r = me.patch(
        f"/objects/user/{q(ASMITH)}",
        {"tabs": {"main": {"values": {"telephoneNumber": "+33 1 23"}}}},
    )
    assert r.status_code == 200, r.text
    r = me.patch(f"/objects/user/{q(ASMITH)}", {"tabs": {"main": {"values": {"sn": "Hacker"}}}})
    assert r.status_code == 403
    assert me.get(f"/objects/user/{q(DLEFEVRE)}").status_code == 403


def test_account_lock_and_listing_badge(app_client: TestClient) -> None:
    helpdesk = api(app_client, "helpdesk")
    r = helpdesk.post(f"/users/{q(ASMITH)}/lock")
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True
    admin = api(app_client, "admin")
    page = admin.get("/objects/user", base=PARIS, scope="one").json()
    locked = {i["dn"]: i["locked"] for i in page["items"]}
    assert locked[ASMITH] is True
    assert admin.get("/dashboard").json()["locked_users"] == 1
    assert helpdesk.post(f"/users/{q(ASMITH)}/unlock").json()["locked"] is False
    # a regular user cannot lock accounts
    assert api(app_client, "bmartin").post(f"/users/{q(ASMITH)}/lock").status_code == 403


def test_snapshots_roundtrip(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.post(f"/objects/user/{q(ASMITH)}/snapshots", {"description": "before change"})
    assert r.status_code == 201, r.text
    snap = r.json()
    a.patch(f"/objects/user/{q(ASMITH)}", {"tabs": {"main": {"values": {"sn": "Changed"}}}})
    listed = a.get(f"/objects/user/{q(ASMITH)}/snapshots").json()
    assert [s["id"] for s in listed] == [snap["id"]]
    assert a.post(f"/snapshots/{q(snap['id'])}/restore").status_code == 200
    assert a.get(f"/objects/user/{q(ASMITH)}").json()["tabs"]["main"]["values"]["sn"] == "Smith"
    assert a.delete(f"/snapshots/{q(snap['id'])}").status_code == 204


def test_logout_releases_locks(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    assert a.post(f"/objects/user/{q(ASMITH)}/lock").status_code == 200
    assert a.post("/auth/logout").status_code == 204
    b = api(app_client, "helpdesk")
    r = b.post(f"/objects/user/{q(ASMITH)}/lock")
    assert r.status_code == 200, r.text


def test_dashboard_counts(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    cards = {c["key"]: c["value"] for c in a.get("/dashboard").json()["cards"]}
    assert cards["user"] == 7
    assert cards["group"] == 2
    assert cards["role"] == 1


def test_posix_plugin_through_api(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    names = {t["name"] for t in a.get("/types").json()}
    assert "posix_group" in names
    tabs = {t["name"]: t for t in a.get("/types/user").json()["tabs"]}
    assert tabs["posix"]["optional"] is True
    r = a.patch(f"/objects/user/{q(ASMITH)}", {"tabs": {"posix": {"active": True, "values": {}}}})
    assert r.status_code == 200, r.text
    posix_values = r.json()["tabs"]["posix"]["values"]
    assert posix_values["uidNumber"] == 1101
    assert posix_values["homeDirectory"] == "/home/asmith"
    assert "rwcdm" in r.json()["acl"]["posix"]["object"]


def test_ssh_keys_follow_account_lock(app_client: TestClient) -> None:
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEN4afpmpx6UcN3RZPI3PaZEelen0CCXeFfX96TNN8Fw me@host"
    a = api(app_client, "admin")
    r = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {
            "tabs": {
                "posix": {"active": True, "values": {}},
                "ssh": {"active": True, "values": {"sshPublicKey": [key]}},
            }
        },
    )
    assert r.status_code == 200, r.text

    def keys() -> list[str]:
        got = a.get(f"/objects/user/{q(ASMITH)}")
        assert got.status_code == 200, got.text
        return got.json()["tabs"]["ssh"]["values"]["sshPublicKey"]

    assert keys() == [key]
    r = a.post(f"/users/{q(ASMITH)}/lock")
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True
    assert keys() == [f"disabled-{key}"]
    page = a.get("/objects/user", base=PARIS, scope="one").json()
    assert {i["dn"]: i["locked"] for i in page["items"]}[ASMITH] is True
    assert a.post(f"/users/{q(ASMITH)}/lock").status_code == 200
    assert keys() == [f"disabled-{key}"]
    r = a.post(f"/users/{q(ASMITH)}/unlock")
    assert r.json()["locked"] is False
    assert keys() == [key]


def test_sudo_type_listed_in_access_category(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    types = {t["name"]: t for t in a.get("/types").json()}
    assert types["sudo"]["category"] == "access"
    tabs = {t["name"]: t for t in a.get("/types/sudo").json()["tabs"]}
    assert set(tabs) == {"main", "options"}


def test_sudo_role_crud_as_admin(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.post(
        "/objects/sudo",
        {
            "base": BASE,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "ops-restart",
                        "sudoUser": ["%admins"],
                        "sudoCommand": ["/usr/bin/systemctl restart *"],
                    }
                },
                "options": {"values": {"sudoOption": ["!authenticate"]}},
            },
        },
    )
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]
    assert dn == f"cn=ops-restart,ou=sudoers,{BASE}"
    main = a.get(f"/objects/sudo/{q(dn)}").json()["tabs"]["main"]["values"]
    assert main["sudoHost"] == ["ALL"]
    assert main["is_default"] is False

    r = a.patch(f"/objects/sudo/{q(dn)}", {"tabs": {"main": {"values": {"sudoOrder": 5}}}})
    assert r.status_code == 200, r.text
    assert r.json()["tabs"]["main"]["values"]["sudoOrder"] == 5

    bad = a.patch(
        f"/objects/sudo/{q(dn)}", {"tabs": {"options": {"values": {"sudoOption": ["bogus"]}}}}
    )
    assert bad.status_code == 422, bad.text

    assert a.delete(f"/objects/sudo/{q(dn)}").status_code == 204
    assert a.get(f"/objects/sudo/{q(dn)}").status_code == 404


def test_sudo_role_forbidden_for_helpdesk(app_client: TestClient) -> None:
    h = api(app_client, "helpdesk")
    r = h.post(
        "/objects/sudo",
        {"base": BASE, "tabs": {"main": {"values": {"cn": "nope", "sudoCommand": ["ALL"]}}}},
    )
    assert r.status_code == 403, r.text


def test_demo_loads_plugins_and_public_routes(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    names = {t["name"] for t in a.get("/types").json()}
    assert {"dns_zone", "server", "reminder_task", "sudo", "posix_group"} <= names
    page = a.get("/objects/server", base=BASE, scope="sub").json()
    assert [i["values"]["cn"] for i in page["items"]] == ["srv-web"]
    # public route: no session, no CSRF token, wrong token -> 400 (not 401/403)
    r = app_client.post("/api/v2/reminder/prolong", json={"login": "jdoe", "token": "nope"})
    assert r.status_code == 400, r.text


def test_changes_are_audited(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.patch(f"/objects/user/{q(ASMITH)}", {"tabs": {"main": {"values": {"sn": "Audited"}}}})
    assert r.status_code == 200, r.text
    events = a.get("/objects/audit_event", base=BASE, scope="sub", limit=500).json()["items"]
    assert events, "no audit event recorded"
    app = cast("FastAPI", app_client.app)
    state = cast("AppState", app.state.heracles)
    directory = state.directories["main"]
    found = [
        e
        for e in directory.search(BASE, "(objectClass=hrcAuditEvent)")
        if (e.text("hrcAuditObject") or "").lower() == ASMITH.lower()
    ]
    assert found
    assert found[-1].text("hrcAuditAuthorDN") == f"uid=admin,ou=people,{BASE}"
    assert "sn" in " ".join(found[-1].texts("hrcAuditAttributes"))


def test_password_policy_violation_is_a_validation_error(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.patch(
        f"/objects/user/{q(ASMITH)}", {"tabs": {"main": {"values": {"userPassword": "abc"}}}}
    )
    assert r.status_code == 422, r.text
    assert "main.userPassword" in r.json()["error"]["fields"]
    r = a.patch(
        f"/objects/user/{q(ASMITH)}",
        {"tabs": {"main": {"values": {"userPassword": "long-enough-secret"}}}},
    )
    assert r.status_code == 200, r.text
