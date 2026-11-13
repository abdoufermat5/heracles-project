"""Unit and integration tests for the Dovecot plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.dovecot as dovecot
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
    "hrcDovecotServer",
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
    status_dovecot = registry.register_plugin(dovecot.plugin(), schema_classes)
    assert status_dovecot.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_dovecot_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("dovecot")
    assert tab is not None
    assert tab.acl_key == "serviceDovecot"
    assert server_info.acl_object(tab) == "server/serviceDovecot"
    assert tab.optional is True
    assert tab.object_classes == ("hrcDovecotServer",)


def test_dovecot_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(dovecot.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("dovecot") is None


def test_create_server_with_dovecot_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail1"}},
            "dovecot": {
                "active": True,
                "values": {
                    "hrcDovecotConnectURL": "imap.example.com",
                    "hrcDovecotConnectPort": 993,
                    "hrcDovecotConnectOptions1": "/ssl",
                    "hrcDovecotConnectOptions2": "/novalidate-cert",
                    "hrcDovecotAdmin": "dovecotadmin",
                    "hrcDovecotPassword": "secretpassword",
                },
            },
        },
    )
    assert dn == f"cn=mail1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcDovecotServer" in entry.get("objectClass")
    assert entry.text("hrcDovecotConnectURL") == "imap.example.com"
    assert entry.text("hrcDovecotConnectPort") == "993"
    assert entry.text("hrcDovecotConnectOptions1") == "/ssl"
    assert entry.text("hrcDovecotConnectOptions2") == "/novalidate-cert"
    assert entry.text("hrcDovecotAdmin") == "dovecotadmin"
    assert entry.text("hrcDovecotPassword") == "secretpassword"

    loaded = service.load("server", dn)
    assert loaded.tabs["dovecot"].active is True
    vals = loaded.tabs["dovecot"].values
    assert vals["hrcDovecotConnectURL"] == "imap.example.com"
    assert vals["hrcDovecotConnectPort"] == 993
    assert vals["hrcDovecotConnectOptions1"] == "/ssl"
    assert vals["hrcDovecotConnectOptions2"] == "/novalidate-cert"
    assert vals["hrcDovecotAdmin"] == "dovecotadmin"
    assert vals["hrcDovecotPassword"] is None  # write-only: never sent back


def test_update_and_deactivate_dovecot_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail2"}},
            "dovecot": {
                "active": True,
                "values": {
                    "hrcDovecotConnectURL": "imap2.example.com",
                    "hrcDovecotConnectPort": 143,
                    "hrcDovecotConnectOptions1": "/tls",
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "dovecot": {
                "values": {
                    "hrcDovecotConnectPort": 993,
                    "hrcDovecotConnectOptions1": "/ssl",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["dovecot"].values["hrcDovecotConnectPort"] == 993
    assert loaded.tabs["dovecot"].values["hrcDovecotConnectOptions1"] == "/ssl"

    # Deactivate tab
    service.update("server", dn, {"dovecot": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcDovecotServer" not in entry.get("objectClass")
    assert entry.get("hrcDovecotConnectURL") == []
    assert entry.get("hrcDovecotConnectPort") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["dovecot"].active is False


def test_dovecot_validation(service: ObjectService) -> None:
    # Invalid port (< 1)
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmail"}},
                "dovecot": {
                    "active": True,
                    "values": {"hrcDovecotConnectPort": 0},
                },
            },
        )
    assert "hrcDovecotConnectPort" in str(exc_info.value)

    # Invalid port (> 65535)
    with pytest.raises(ObjectValidationError) as exc_info2:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmail2"}},
                "dovecot": {
                    "active": True,
                    "values": {"hrcDovecotConnectPort": 70000},
                },
            },
        )
    assert "hrcDovecotConnectPort" in str(exc_info2.value)


def test_mail_servers_helper(service: ObjectService, directory: MemoryDirectory) -> None:
    assert dovecot.mail_servers(directory) == []

    # Create server without dovecot
    service.create("server", BASE, {"main": {"values": {"cn": "plain-server"}}})
    assert dovecot.mail_servers(directory) == []

    # Create server with dovecot
    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail-a"}},
            "dovecot": {"active": True, "values": {"hrcDovecotConnectURL": "mail-a.test"}},
        },
    )
    assert dovecot.mail_servers(directory) == ["mail-a"]

    # Create another server with dovecot
    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail-b"}},
            "dovecot": {"active": True, "values": {"hrcDovecotConnectURL": "mail-b.test"}},
        },
    )
    assert dovecot.mail_servers(directory) == ["mail-a", "mail-b"]


def test_admin_password_is_write_only_and_kept_when_empty(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mail-pw"}},
            "dovecot": {"active": True, "values": {"hrcDovecotPassword": "first-secret"}},
        },
    )
    assert service.load("server", dn).tabs["dovecot"].values["hrcDovecotPassword"] is None
    assert (directory.get(dn) or pytest.fail()).text("hrcDovecotPassword") == "first-secret"

    service.update("server", dn, {"dovecot": {"values": {"hrcDovecotPassword": ""}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcDovecotPassword") == "first-secret"

    service.update("server", dn, {"dovecot": {"values": {"hrcDovecotPassword": "second-secret"}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcDovecotPassword") == "second-secret"
