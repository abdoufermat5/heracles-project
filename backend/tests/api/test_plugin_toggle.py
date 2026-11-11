"""``PATCH /api/v2/admin/plugins/{name}``: live activation of a plugin."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings, DatabaseSettings, PluginsSettings
from heracles.api.state import AppState
from heracles.server import create_full_app
from tests.api.test_admin_api import Api


def build(tmp_path: Path) -> TestClient:
    settings = ApiSettings(
        directory_labels={"main": "Demo"},
        plugins=PluginsSettings(enabled=["posix", "acl_admin"]),
        database=DatabaseSettings(path=tmp_path / "app.db"),
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": demo.build_demo_directory()})
    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with build(tmp_path) as c:
        yield c


def patch(api: Api, name: str, enabled: bool) -> Any:
    return api.client.patch(
        f"/api/v2/admin/plugins/{name}", json={"enabled": enabled}, headers=api.headers
    )


def type_names(api: Api) -> set[str]:
    return {t["name"] for t in api.client.get("/api/v2/types").json()}


def test_listing_distinguishes_available_from_enabled(client: TestClient) -> None:
    rows = {p["name"]: p for p in Api(client).login("admin").get("/plugins").json()}
    assert rows["posix"]["enabled"] and rows["posix"]["available"]
    assert not rows["dns"]["enabled"] and rows["dns"]["available"]
    assert rows["acl_admin"]["locked"]


def test_toggle_takes_effect_without_restart(client: TestClient) -> None:
    admin = Api(client).login("admin")
    before = type_names(admin)
    assert "dns_zone" not in before
    r = patch(admin, "dns", True)
    assert r.status_code == 200, r.text
    assert r.json()["restart_required"] is False
    assert r.json()["plugin"]["enabled"] is True
    assert "dns_zone" in type_names(admin)
    assert {p["name"]: p for p in admin.get("/plugins").json()}["dns"]["enabled"]
    assert patch(admin, "dns", False).status_code == 200
    assert type_names(admin) == before


def test_override_survives_a_restart(tmp_path: Path) -> None:
    with build(tmp_path) as first:
        assert patch(Api(first).login("admin"), "dns", True).status_code == 200
    with build(tmp_path) as second:
        rows = {p["name"]: p for p in Api(second).login("admin").get("/plugins").json()}
        assert rows["dns"]["enabled"]


def test_disabled_plugin_routes_answer_404_until_enabled(client: TestClient) -> None:
    admin = Api(client).login("admin")
    url = "/api/v2/ldif/export"
    off = admin.client.get(url, params={"base": demo.BASE})
    assert off.status_code == 404 and off.json()["error"]["message"] == "This feature is disabled"
    assert patch(admin, "ldapmanager", True).status_code == 200
    assert admin.client.get(url, params={"base": demo.BASE}).status_code != 404
    assert patch(admin, "ldapmanager", False).status_code == 200
    assert admin.client.get(url, params={"base": demo.BASE}).status_code == 404


def test_requires_config_write(client: TestClient) -> None:
    assert patch(Api(client), "dns", True).status_code in (401, 403)
    assert patch(Api(client).login("helpdesk"), "dns", True).status_code == 403
    assert patch(Api(client).login("bmartin"), "dns", True).status_code == 403


def test_errors(client: TestClient) -> None:
    admin = Api(client).login("admin")
    assert patch(admin, "nope", True).status_code == 404
    assert patch(admin, "acl_admin", False).status_code == 409
    r = admin.client.patch("/api/v2/admin/plugins/dns", json={}, headers=admin.headers)
    assert r.status_code == 422


def test_audit_sink_follows_the_audit_plugin_switch(client: TestClient) -> None:
    """Sign-ins are audited as soon as the plugin is switched on, and the switch itself too."""
    admin = Api(client).login("admin")
    app = cast(FastAPI, client.app)
    state: AppState = app.state.heracles
    sink = state.audit
    assert not sink.enabled
    assert patch(admin, "audit", True).status_code == 200
    assert sink.enabled
    events = admin.client.get("/api/v2/audit", params={"action": "config"}).json()["items"]
    assert any("plugin audit enabled" in line for e in events for line in e["attributes"])
    assert patch(admin, "audit", False).status_code == 200
    assert not sink.enabled
    assert patch(admin, "audit", True).status_code == 200
    events = admin.client.get("/api/v2/audit", params={"action": "config"}).json()["items"]
    assert any("plugin audit disabled" in line for e in events for line in e["attributes"])
