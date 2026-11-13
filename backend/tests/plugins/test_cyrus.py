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
    "hrcServer",
    "hrcCyrusServer",
    "ipHost",
    "hrcNetworkInterface",
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
    assert tab.object_classes == ("hrcCyrusServer",)


def test_cyrus_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
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
                    "hrcCyrusConnectURL": "cyrus.example.com",
                    "hrcCyrusConnectPort": 993,
                    "hrcCyrusConnectOptions1": "/ssl",
                    "hrcCyrusConnectOptions2": "/validate-cert",
                    "hrcCyrusAdmin": "cyrusadmin",
                    "hrcCyrusPassword": "cyruspassword",
                    "hrcCyrusUseSlashes": True,
                    "hrcCyrusAutocreateFolders": "Drafts,Sent,Trash,Archive",
                },
            },
        },
    )
    assert dn == f"cn=cyrus1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcCyrusServer" in entry.get("objectClass")
    assert entry.text("hrcCyrusConnectURL") == "cyrus.example.com"
    assert entry.text("hrcCyrusConnectPort") == "993"
    assert entry.text("hrcCyrusConnectOptions1") == "/ssl"
    assert entry.text("hrcCyrusConnectOptions2") == "/validate-cert"
    assert entry.text("hrcCyrusAdmin") == "cyrusadmin"
    assert entry.text("hrcCyrusPassword") == "cyruspassword"
    assert entry.text("hrcCyrusUseSlashes") == "TRUE"
    assert entry.text("hrcCyrusAutocreateFolders") == "Drafts,Sent,Trash,Archive"

    loaded = service.load("server", dn)
    assert loaded.tabs["cyrus"].active is True
    vals = loaded.tabs["cyrus"].values
    assert vals["hrcCyrusConnectURL"] == "cyrus.example.com"
    assert vals["hrcCyrusConnectPort"] == 993
    assert vals["hrcCyrusConnectOptions1"] == "/ssl"
    assert vals["hrcCyrusConnectOptions2"] == "/validate-cert"
    assert vals["hrcCyrusAdmin"] == "cyrusadmin"
    assert vals["hrcCyrusPassword"] is None  # write-only: never sent back
    assert vals["hrcCyrusUseSlashes"] is True
    assert vals["hrcCyrusAutocreateFolders"] == "Drafts,Sent,Trash,Archive"


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
                    "hrcCyrusConnectURL": "cyrus2.example.com",
                    "hrcCyrusConnectPort": 143,
                    "hrcCyrusConnectOptions1": "/tls",
                    "hrcCyrusUseSlashes": False,
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
                    "hrcCyrusConnectPort": 993,
                    "hrcCyrusConnectOptions1": "/ssl",
                    "hrcCyrusUseSlashes": True,
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["cyrus"].values["hrcCyrusConnectPort"] == 993
    assert loaded.tabs["cyrus"].values["hrcCyrusConnectOptions1"] == "/ssl"
    assert loaded.tabs["cyrus"].values["hrcCyrusUseSlashes"] is True

    # Deactivate tab
    service.update("server", dn, {"cyrus": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcCyrusServer" not in entry.get("objectClass")
    assert entry.get("hrcCyrusConnectURL") == []
    assert entry.get("hrcCyrusConnectPort") == []
    assert entry.get("hrcCyrusUseSlashes") == []

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
                    "values": {"hrcCyrusConnectPort": 0},
                },
            },
        )
    assert "hrcCyrusConnectPort" in str(exc_info.value)


def test_mail_servers_helper_cyrus(service: ObjectService, directory: MemoryDirectory) -> None:
    assert cyrus.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "cyrus-srv"}}})
    assert cyrus.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "cyrus-mail"}},
            "cyrus": {"active": True, "values": {"hrcCyrusConnectURL": "cyrus.test"}},
        },
    )
    assert cyrus.mail_servers(directory) == ["cyrus-mail"]


def test_admin_password_is_write_only_and_kept_when_empty(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "cyrus-pw"}},
            "cyrus": {"active": True, "values": {"hrcCyrusPassword": "first-secret"}},
        },
    )
    assert service.load("server", dn).tabs["cyrus"].values["hrcCyrusPassword"] is None
    assert (directory.get(dn) or pytest.fail()).text("hrcCyrusPassword") == "first-secret"

    # An empty value keeps the stored password (the field is write-only: it reads as empty).
    service.update("server", dn, {"cyrus": {"values": {"hrcCyrusPassword": ""}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcCyrusPassword") == "first-secret"

    service.update("server", dn, {"cyrus": {"values": {"hrcCyrusPassword": "second-secret"}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcCyrusPassword") == "second-secret"
