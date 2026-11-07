"""``POST /api/v2/archive/{type}/{dn}`` on the demo application with the archive schema."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app

BASE = demo.BASE
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
BMARTIN = f"uid=bmartin,ou=people,ou=paris,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"


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


@pytest.fixture
def directory() -> MemoryDirectory:
    d = demo.build_demo_directory()
    d.set_schema_object_classes([*d.schema_object_classes(), "fdArchivedObject", "fdArchiveTasks"])
    return d


@pytest.fixture
def app_client(directory: MemoryDirectory) -> Iterator[TestClient]:
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


def test_admin_archives_a_user(app_client: TestClient, directory: MemoryDirectory) -> None:
    a = Api(app_client).login("admin")
    r = a.post(f"/archive/user/{q(ASMITH)}")
    assert r.status_code == 201, r.text
    dn = r.json()["dn"]
    assert dn.startswith("cn=user_asmith_") and dn.endswith(f"ou=archive,{BASE}")
    entry = directory.get(dn)
    assert entry is not None and entry.text("fdArchivedOriginDn") == ASMITH
    assert directory.get(ASMITH) is not None
    # the archive is visible through the generic API
    listed = a.get("/objects/archived_object").json()
    assert listed["total"] == 1
    assert a.get(f"/objects/archived_object/{q(dn)}").status_code == 200


def test_requires_authentication(app_client: TestClient) -> None:
    api = Api(app_client)
    assert api.post(f"/archive/user/{q(ASMITH)}").status_code == 401


def test_requires_delete_rights(app_client: TestClient) -> None:
    helpdesk = Api(app_client).login("helpdesk")
    assert helpdesk.post(f"/archive/user/{q(ASMITH)}").status_code == 403
    regular = Api(app_client).login("bmartin")
    assert regular.post(f"/archive/user/{q(BMARTIN)}").status_code == 403


def test_delegated_manager_can_archive_in_scope_only(app_client: TestClient) -> None:
    lyon_manager = Api(app_client).login("cdupont")
    assert lyon_manager.post(f"/archive/user/{q(CDUPONT)}").status_code == 201
    assert lyon_manager.post(f"/archive/user/{q(ASMITH)}").status_code == 403


def test_errors(app_client: TestClient) -> None:
    a = Api(app_client).login("admin")
    assert a.post(f"/archive/nope/{q(ASMITH)}").status_code == 404
    assert a.post(f"/archive/user/{q('uid=ghost,ou=people,' + BASE)}").status_code == 404
    # an existing object of another type
    r = a.post(f"/archive/user/{q('cn=admins,ou=groups,' + BASE)}")
    assert r.status_code == 404
    # a type without archive rule
    r = a.post(f"/archive/role/{q('cn=lyon-managers,ou=roles,ou=lyon,' + BASE)}")
    assert r.status_code == 422
