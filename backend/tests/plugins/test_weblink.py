"""Tests for the Weblink plugin (hrcWebLinkAccount tab on server, workstation, etc.)."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.systems as systems
import heracles_plugins.weblink as weblink
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.names import OC, PLUGIN_OBJECT_CLASSES

BASE = "dc=test"
PARIS = f"ou=paris,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"domain"], "dc": [b"test"]})
    d.add(
        PARIS,
        {
            "objectClass": [b"top", b"organizationalUnit", OC.DEPARTMENT.encode()],
            "ou": [b"paris"],
        },
    )
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            *PLUGIN_OBJECT_CLASSES,
            "hrcWebLinkAccount",
        ]
    )
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    classes = {c.lower() for c in directory.schema_object_classes()}
    reg.register_plugin(systems.plugin(), classes)
    status = reg.register_plugin(weblink.plugin(), classes)
    assert status.enabled
    return reg


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def test_weblink_on_server(service: ObjectService, directory: MemoryDirectory) -> None:
    srv_values: dict[str, Any] = {
        "cn": "srv-web",
        "description": "Web server",
    }
    weblink_values: dict[str, Any] = {
        "hrcWebLinkProtocol": "https://",
        "hrcWebLinkURL": "admin.example.com/dashboard",
    }
    tabs = {
        "main": {"values": srv_values},
        "weblink": {"active": True, "values": weblink_values},
    }
    dn = service.create("server", PARIS, tabs)

    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("hrcWebLinkAccount")
    assert entry.text("hrcWebLinkProtocol") == "https://"
    assert entry.text("hrcWebLinkURL") == "admin.example.com/dashboard"
    assert entry.text("hrcWebLink") == "https://admin.example.com/dashboard"

    loaded = service.load("server", dn)
    assert loaded.tabs["weblink"].active is True
    assert loaded.tabs["weblink"].values["hrcWebLink"] == "https://admin.example.com/dashboard"

    # Update protocol to http://
    service.update(
        "server",
        dn,
        {
            "weblink": {
                "values": {
                    "hrcWebLinkProtocol": "http://",
                    "hrcWebLinkURL": "intranet.local",
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("hrcWebLink") == "http://intranet.local"

    # Deactivate weblink tab
    service.update("server", dn, {"weblink": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("hrcWebLinkAccount")
    assert entry.get("hrcWebLink") == []


def test_weblink_with_full_url(service: ObjectService, directory: MemoryDirectory) -> None:
    tabs = {
        "main": {"values": {"cn": "ws-01"}},
        "weblink": {
            "active": True,
            "values": {
                "hrcWebLinkURL": "https://console.example.org:8443",
            },
        },
    }
    dn = service.create("workstation", PARIS, tabs)
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("hrcWebLink") == "https://console.example.org:8443"
