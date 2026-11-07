"""Unit and integration tests for the Cyrus plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.cyrus as cyrus
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"

CYRUS_CLASSES = {
    "ieee802Device",
    "device",
    "fdServer",
    "fdCyrusServer",
    "ipHost",
    "fdNetworkInterface",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=CYRUS_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status_sys = registry.register_plugin(systems.plugin(), schema_classes)
    assert status_sys.enabled
    status_cyrus = registry.register_plugin(cyrus.plugin(), schema_classes)
    assert status_cyrus.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_cyrus_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("cyrus")
    assert tab is not None
    assert tab.acl_key == "serviceCyrus"
    assert server_info.acl_object(tab) == "server/serviceCyrus"
    assert tab.optional is True
    assert tab.object_classes == ("fdCyrusServer",)


def test_cyrus_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "fdServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(cyrus.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("cyrus") is None


def test_create_server_with_cyrus_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "cyrus1"}},
            "cyrus": {
                "active": True,
                "values": {
                    "cyrusConnectURL": "cyrus.example.com",
                    "cyrusConnectPort": 993,
                    "cyrusConnectOptions1": "/ssl",
                    "cyrusConnectOptions2": "/validate-cert",
                    "fdCyrusAdmin": "cyrusadmin",
                    "fdCyrusPassword": "cyruspassword",
                    "fdCyrusUseSlashes": True,
                    "fdCyrusAutocreateFolders": "Drafts,Sent,Trash,Archive",
                },
            },
        },
    )
    assert dn == f"cn=cyrus1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"fdCyrusServer" in entry.get("objectClass")
    assert entry.text("cyrusConnectURL") == "cyrus.example.com"
    assert entry.text("cyrusConnectPort") == "993"
    assert entry.text("cyrusConnectOptions1") == "/ssl"
    assert entry.text("cyrusConnectOptions2") == "/validate-cert"
    assert entry.text("fdCyrusAdmin") == "cyrusadmin"
    assert entry.text("fdCyrusPassword") == "cyruspassword"
    assert entry.text("fdCyrusUseSlashes") == "TRUE"
    assert entry.text("fdCyrusAutocreateFolders") == "Drafts,Sent,Trash,Archive"

    loaded = service.load("server", dn)
    assert loaded.tabs["cyrus"].active is True
    vals = loaded.tabs["cyrus"].values
    assert vals["cyrusConnectURL"] == "cyrus.example.com"
    assert vals["cyrusConnectPort"] == 993
    assert vals["cyrusConnectOptions1"] == "/ssl"
    assert vals["cyrusConnectOptions2"] == "/validate-cert"
    assert vals["fdCyrusAdmin"] == "cyrusadmin"
    assert vals["fdCyrusPassword"] == "cyruspassword"
    assert vals["fdCyrusUseSlashes"] is True
    assert vals["fdCyrusAutocreateFolders"] == "Drafts,Sent,Trash,Archive"


def test_update_and_deactivate_cyrus_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "cyrus2"}},
            "cyrus": {
                "active": True,
                "values": {
                    "cyrusConnectURL": "cyrus2.example.com",
                    "cyrusConnectPort": 143,
                    "cyrusConnectOptions1": "/tls",
                    "fdCyrusUseSlashes": False,
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "cyrus": {
                "values": {
                    "cyrusConnectPort": 993,
                    "cyrusConnectOptions1": "/ssl",
                    "fdCyrusUseSlashes": True,
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["cyrus"].values["cyrusConnectPort"] == 993
    assert loaded.tabs["cyrus"].values["cyrusConnectOptions1"] == "/ssl"
    assert loaded.tabs["cyrus"].values["fdCyrusUseSlashes"] is True

    # Deactivate tab
    service.update("server", dn, {"cyrus": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"fdCyrusServer" not in entry.get("objectClass")
    assert entry.get("cyrusConnectURL") == []
    assert entry.get("cyrusConnectPort") == []
    assert entry.get("fdCyrusUseSlashes") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["cyrus"].active is False


def test_cyrus_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badcyrus"}},
                "cyrus": {
                    "active": True,
                    "values": {"cyrusConnectPort": 0},
                },
            },
        )
    assert "cyrusConnectPort" in str(exc_info.value)


def test_mail_servers_helper_cyrus(service: ObjectService, directory: MemoryDirectory) -> None:
    assert cyrus.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "cyrus-srv"}}})
    assert cyrus.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "cyrus-mail"}},
            "cyrus": {"active": True, "values": {"cyrusConnectURL": "cyrus.test"}},
        },
    )
    assert cyrus.mail_servers(directory) == ["cyrus-mail"]
