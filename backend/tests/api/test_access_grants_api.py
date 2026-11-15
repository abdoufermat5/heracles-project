"""``/api/v2/access/grants``: end dates through the API, with the editors' rights."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings, PluginsSettings
from heracles.core.access_config import configure_access
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app
from heracles_plugins.access import grants as g
from tests.api.test_audit_api import Api

BASE = demo.BASE
ADMINS = f"cn=admins,ou=groups,{BASE}"
LYON_STAFF = f"cn=lyon-staff,ou=groups,ou=lyon,{BASE}"
ADMIN = f"uid=admin,ou=people,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"


@pytest.fixture(autouse=True)
def _config() -> Iterator[None]:
    configure_access({"max_days": 90})
    yield
    configure_access(None)


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


@pytest.fixture
def client(directory: MemoryDirectory) -> Iterator[TestClient]:
    settings = ApiSettings(
        admin_dns=[], directory_labels={"main": "Demo"}, plugins=PluginsSettings(enabled=["*"])
    )
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as c:
        yield c


def soon(days: int = 10) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


def test_admin_dates_a_membership_and_reads_it_back(
    client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(client)
    a.login("admin")
    r = a.put(
        "/access/grants",
        {"holder": LYON_STAFF, "kind": "member", "member": CDUPONT, "until": soon()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["grant"]["until"].endswith("23:59:59+00:00")
    items = a.get("/access/grants", holder=LYON_STAFF).json()["items"]
    assert [(i["member"], i["kind"]) for i in items] == [(CDUPONT, "member")]
    assert a.get("/access/grants", member=CDUPONT).json()["items"] == items
    entry = directory.get(LYON_STAFF)
    assert entry is not None and len(entry.texts(g.GRANT_ATTR)) == 1
    # an audit event names the change
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditObjectType=grant)"))
    assert events and f"member: {CDUPONT}" in events[0].texts("hrcAuditAttributes")


def test_dates_are_checked(client: TestClient) -> None:
    a = Api(client)
    a.login("admin")
    body = {"holder": LYON_STAFF, "kind": "member", "member": CDUPONT}
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert a.put("/access/grants", {**body, "until": past}).status_code == 422
    assert a.put("/access/grants", {**body, "until": soon(200)}).status_code == 422
    cleared = a.put("/access/grants", {**body, "until": None})  # editors may make it permanent
    assert cleared.status_code == 200 and cleared.json() == {"grant": None}
    assert a.put("/access/grants", {**body, "member": ADMIN, "until": soon()}).status_code == 422


def test_people_without_write_rights_cannot_date(client: TestClient) -> None:
    a = Api(client)
    a.login("asmith")
    r = a.put(
        "/access/grants", {"holder": ADMINS, "kind": "member", "member": ADMIN, "until": soon()}
    )
    assert r.status_code == 403


def test_my_end_dates(client: TestClient, directory: MemoryDirectory) -> None:
    g.set_end_date(directory, LYON_STAFF, "member", CDUPONT, datetime.now(UTC) + timedelta(days=5))
    a = Api(client)
    a.login("cdupont")
    items = a.get("/access/me").json()["items"]
    assert [i["holder"] for i in items] == [LYON_STAFF]


def test_removing_a_member_drops_its_date(client: TestClient, directory: MemoryDirectory) -> None:
    g.set_end_date(directory, LYON_STAFF, "member", CDUPONT, datetime.now(UTC) + timedelta(days=5))
    a = Api(client)
    a.login("admin")
    from urllib.parse import quote

    path = f"/objects/group/{quote(LYON_STAFF, safe='')}"
    current = a.get(path).json()
    members = [m for m in current["tabs"]["main"]["values"]["member"] if m != CDUPONT]
    r = a.client.patch(
        f"/api/v2{path}",
        json={"tabs": {"main": {"values": {"member": members}}}},
        headers=a.headers,
    )
    assert r.status_code == 200, r.text
    entry = directory.get(LYON_STAFF)
    assert entry is not None and entry.texts(g.GRANT_ATTR) == []


def test_status_probe_needs_a_session(client: TestClient) -> None:
    a = Api(client)
    assert a.get("/access/status").status_code == 401
    a.login("asmith")
    assert a.get("/access/status").json() == {"enabled": True}
