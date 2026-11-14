"""Unit and integration tests for the IMAP mailbox plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.imap_mailbox as imap_mailbox
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"

DOVECOT_CLASSES = {
    "ieee802Device",
    "device",
    "hrcServer",
    "hrcImapServer",
    "ipHost",
    "hrcNetworkInterface",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=DOVECOT_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status_sys = registry.register_plugin(systems.plugin(), schema_classes)
    assert status_sys.enabled
    status_imap_mailbox = registry.register_plugin(imap_mailbox.plugin(), schema_classes)
    assert status_imap_mailbox.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_imap_mailbox_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("imap_mailbox")
    assert tab is not None
    assert tab.acl_key == "serviceImap"
    assert server_info.acl_object(tab) == "server/serviceImap"
    assert tab.optional is True
    assert tab.object_classes == ("hrcImapServer",)


def test_imap_mailbox_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(imap_mailbox.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("imap_mailbox") is None


def test_create_server_with_imap_mailbox_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail1"}},
            "imap_mailbox": {
                "active": True,
                "values": {
                    "hrcImapConnectURL": "imap.example.com",
                    "hrcImapConnectPort": 993,
                    "hrcImapConnectOptions1": "/ssl",
                    "hrcImapConnectOptions2": "/novalidate-cert",
                    "hrcImapAdmin": "imap_mailboxadmin",
                    "hrcImapPassword": "secretpassword",
                },
            },
        },
    )
    assert dn == f"cn=mail1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcImapServer" in entry.get("objectClass")
    assert entry.text("hrcImapConnectURL") == "imap.example.com"
    assert entry.text("hrcImapConnectPort") == "993"
    assert entry.text("hrcImapConnectOptions1") == "/ssl"
    assert entry.text("hrcImapConnectOptions2") == "/novalidate-cert"
    assert entry.text("hrcImapAdmin") == "imap_mailboxadmin"
    assert entry.text("hrcImapPassword") == "secretpassword"

    loaded = service.load("server", dn)
    assert loaded.tabs["imap_mailbox"].active is True
    vals = loaded.tabs["imap_mailbox"].values
    assert vals["hrcImapConnectURL"] == "imap.example.com"
    assert vals["hrcImapConnectPort"] == 993
    assert vals["hrcImapConnectOptions1"] == "/ssl"
    assert vals["hrcImapConnectOptions2"] == "/novalidate-cert"
    assert vals["hrcImapAdmin"] == "imap_mailboxadmin"
    assert vals["hrcImapPassword"] is None  # write-only: never sent back


def test_update_and_deactivate_imap_mailbox_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail2"}},
            "imap_mailbox": {
                "active": True,
                "values": {
                    "hrcImapConnectURL": "imap2.example.com",
                    "hrcImapConnectPort": 143,
                    "hrcImapConnectOptions1": "/tls",
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "imap_mailbox": {
                "values": {
                    "hrcImapConnectPort": 993,
                    "hrcImapConnectOptions1": "/ssl",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["imap_mailbox"].values["hrcImapConnectPort"] == 993
    assert loaded.tabs["imap_mailbox"].values["hrcImapConnectOptions1"] == "/ssl"

    # Deactivate tab
    service.update("server", dn, {"imap_mailbox": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcImapServer" not in entry.get("objectClass")
    assert entry.get("hrcImapConnectURL") == []
    assert entry.get("hrcImapConnectPort") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["imap_mailbox"].active is False


def test_imap_mailbox_validation(service: ObjectService) -> None:
    # Invalid port (< 1)
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmail"}},
                "imap_mailbox": {
                    "active": True,
                    "values": {"hrcImapConnectPort": 0},
                },
            },
        )
    assert "hrcImapConnectPort" in str(exc_info.value)

    # Invalid port (> 65535)
    with pytest.raises(ObjectValidationError) as exc_info2:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmail2"}},
                "imap_mailbox": {
                    "active": True,
                    "values": {"hrcImapConnectPort": 70000},
                },
            },
        )
    assert "hrcImapConnectPort" in str(exc_info2.value)


def test_mail_servers_helper(service: ObjectService, directory: MemoryDirectory) -> None:
    assert imap_mailbox.mail_servers(directory) == []

    # Create server without imap_mailbox
    service.create("server", BASE, {"main": {"values": {"cn": "plain-server"}}})
    assert imap_mailbox.mail_servers(directory) == []

    # Create server with imap_mailbox
    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail-a"}},
            "imap_mailbox": {"active": True, "values": {"hrcImapConnectURL": "mail-a.test"}},
        },
    )
    assert imap_mailbox.mail_servers(directory) == ["mail-a"]

    # Create another server with imap_mailbox
    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail-b"}},
            "imap_mailbox": {"active": True, "values": {"hrcImapConnectURL": "mail-b.test"}},
        },
    )
    assert imap_mailbox.mail_servers(directory) == ["mail-a", "mail-b"]


def test_admin_password_is_write_only_and_kept_when_empty(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail-pw"}},
            "imap_mailbox": {"active": True, "values": {"hrcImapPassword": "first-secret"}},
        },
    )
    assert service.load("server", dn).tabs["imap_mailbox"].values["hrcImapPassword"] is None
    assert (directory.get(dn) or pytest.fail()).text("hrcImapPassword") == "first-secret"

    service.update("server", dn, {"imap_mailbox": {"values": {"hrcImapPassword": ""}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcImapPassword") == "first-secret"

    service.update("server", dn, {"imap_mailbox": {"values": {"hrcImapPassword": "second-secret"}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcImapPassword") == "second-secret"
