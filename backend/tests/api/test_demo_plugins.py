"""The demo directory schema supports every first-party plugin."""

from __future__ import annotations

from collections.abc import Iterator
from importlib.metadata import entry_points
from typing import Any

import pytest
from fastapi.testclient import TestClient

from heracles.demo import build_demo_directory
from heracles.objects.registry import PLUGIN_GROUP
from heracles.server import build_demo_app
from tests.api.test_objects_flow import Api


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    with TestClient(build_demo_app()) as client:
        yield client


def test_types_list_plugin_types_and_user_tabs(app_client: TestClient) -> None:
    admin = Api(app_client).login("admin")
    r = admin.get("/types")
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()}
    assert {"ppolicy", "mail_alias_redirection", "mail_alias_distribution"} <= names
    assert "dhcp_configuration" in names
    nav = {t["name"]: (t["nav"], t["nav_group"]) for t in r.json()}
    assert all(v[0] == "hidden" for k, v in nav.items() if k.endswith("_task"))
    assert nav["mail_alias_redirection"] == ("secondary", "mail")

    user = admin.get("/types/user").json()
    tabs = {t["name"]: t for t in user["tabs"]}
    assert {"personal", "mail", "ppolicy"} <= set(tabs)
    assert tabs["ppolicy"]["optional"] is False
    assert tabs["mail"]["optional"] is True


def test_every_plugin_is_enabled_and_registers_all_its_types() -> None:
    directory = build_demo_directory()
    available = {c.lower() for c in directory.schema_object_classes()}
    for point in entry_points(group=PLUGIN_GROUP):
        plugin: Any = point.load()()
        assert not plugin.missing_object_classes(available), point.name
        for type_cls in plugin.types:
            needed = type_cls.required_object_classes or type_cls.tabs[0].object_classes
            assert all(c.lower() in available for c in needed), (point.name, type_cls.name)
