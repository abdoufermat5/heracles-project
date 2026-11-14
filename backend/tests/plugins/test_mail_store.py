"""Unit and integration tests for the Mail store plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.mail_store as mail_store
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
    "hrcMailStoreServer",
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
    status_mail_store = registry.register_plugin(mail_store.plugin(), schema_classes)
    assert status_mail_store.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_mail_store_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("mail_store")
    assert tab is not None
    assert tab.acl_key == "serviceMailStore"
    assert server_info.acl_object(tab) == "server/serviceMailStore"
    assert tab.optional is True
    assert tab.object_classes == ("hrcMailStoreServer",)


def test_mail_store_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(mail_store.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("mail_store") is None


def test_create_server_with_mail_store_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mailstore1"}},
            "mail_store": {
                "active": True,
                "values": {
                    "hrcMailStoreConnectURL": "mail_store.example.com",
                    "hrcMailStoreConnectPort": 993,
                    "hrcMailStoreConnectOptions1": "/ssl",
                    "hrcMailStoreConnectOptions2": "/validate-cert",
                    "hrcMailStoreAdmin": "mail_storeadmin",
                    "hrcMailStorePassword": "mail_storepassword",
                    "hrcMailStoreUseSlashes": True,
                    "hrcMailStoreAutocreateFolders": "Drafts,Sent,Trash,Archive",
                },
            },
        },
    )
    assert dn == f"cn=mailstore1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcMailStoreServer" in entry.get("objectClass")
    assert entry.text("hrcMailStoreConnectURL") == "mail_store.example.com"
    assert entry.text("hrcMailStoreConnectPort") == "993"
    assert entry.text("hrcMailStoreConnectOptions1") == "/ssl"
    assert entry.text("hrcMailStoreConnectOptions2") == "/validate-cert"
    assert entry.text("hrcMailStoreAdmin") == "mail_storeadmin"
    assert entry.text("hrcMailStorePassword") == "mail_storepassword"
    assert entry.text("hrcMailStoreUseSlashes") == "TRUE"
    assert entry.text("hrcMailStoreAutocreateFolders") == "Drafts,Sent,Trash,Archive"

    loaded = service.load("server", dn)
    assert loaded.tabs["mail_store"].active is True
    vals = loaded.tabs["mail_store"].values
    assert vals["hrcMailStoreConnectURL"] == "mail_store.example.com"
    assert vals["hrcMailStoreConnectPort"] == 993
    assert vals["hrcMailStoreConnectOptions1"] == "/ssl"
    assert vals["hrcMailStoreConnectOptions2"] == "/validate-cert"
    assert vals["hrcMailStoreAdmin"] == "mail_storeadmin"
    assert vals["hrcMailStorePassword"] is None  # write-only: never sent back
    assert vals["hrcMailStoreUseSlashes"] is True
    assert vals["hrcMailStoreAutocreateFolders"] == "Drafts,Sent,Trash,Archive"


def test_update_and_deactivate_mail_store_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mailstore2"}},
            "mail_store": {
                "active": True,
                "values": {
                    "hrcMailStoreConnectURL": "mailstore2.example.com",
                    "hrcMailStoreConnectPort": 143,
                    "hrcMailStoreConnectOptions1": "/tls",
                    "hrcMailStoreUseSlashes": False,
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "mail_store": {
                "values": {
                    "hrcMailStoreConnectPort": 993,
                    "hrcMailStoreConnectOptions1": "/ssl",
                    "hrcMailStoreUseSlashes": True,
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["mail_store"].values["hrcMailStoreConnectPort"] == 993
    assert loaded.tabs["mail_store"].values["hrcMailStoreConnectOptions1"] == "/ssl"
    assert loaded.tabs["mail_store"].values["hrcMailStoreUseSlashes"] is True

    # Deactivate tab
    service.update("server", dn, {"mail_store": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcMailStoreServer" not in entry.get("objectClass")
    assert entry.get("hrcMailStoreConnectURL") == []
    assert entry.get("hrcMailStoreConnectPort") == []
    assert entry.get("hrcMailStoreUseSlashes") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["mail_store"].active is False


def test_mail_store_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmailstore"}},
                "mail_store": {
                    "active": True,
                    "values": {"hrcMailStoreConnectPort": 0},
                },
            },
        )
    assert "hrcMailStoreConnectPort" in str(exc_info.value)


def test_mail_servers_helper_mail_store(service: ObjectService, directory: MemoryDirectory) -> None:
    assert mail_store.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "mailstore-srv"}}})
    assert mail_store.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mailstore-mail"}},
            "mail_store": {"active": True, "values": {"hrcMailStoreConnectURL": "mail_store.test"}},
        },
    )
    assert mail_store.mail_servers(directory) == ["mailstore-mail"]


def test_admin_password_is_write_only_and_kept_when_empty(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mailstore-pw"}},
            "mail_store": {"active": True, "values": {"hrcMailStorePassword": "first-secret"}},
        },
    )
    assert service.load("server", dn).tabs["mail_store"].values["hrcMailStorePassword"] is None
    assert (directory.get(dn) or pytest.fail()).text("hrcMailStorePassword") == "first-secret"

    # An empty value keeps the stored password (the field is write-only: it reads as empty).
    service.update("server", dn, {"mail_store": {"values": {"hrcMailStorePassword": ""}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcMailStorePassword") == "first-secret"

    service.update(
        "server", dn, {"mail_store": {"values": {"hrcMailStorePassword": "second-secret"}}}
    )
    assert (directory.get(dn) or pytest.fail()).text("hrcMailStorePassword") == "second-secret"
