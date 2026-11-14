"""Unit and integration tests for the Mail transport plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.mail_transport as mail_transport
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"

POSTFIX_CLASSES = {
    "ieee802Device",
    "device",
    "hrcServer",
    "hrcMtaServer",
    "ipHost",
    "hrcNetworkInterface",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=POSTFIX_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status_sys = registry.register_plugin(systems.plugin(), schema_classes)
    assert status_sys.enabled
    status_mail_transport = registry.register_plugin(mail_transport.plugin(), schema_classes)
    assert status_mail_transport.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_mail_transport_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("mail_transport")
    assert tab is not None
    assert tab.acl_key == "serviceMailTransport"
    assert server_info.acl_object(tab) == "server/serviceMailTransport"
    assert tab.optional is True
    assert tab.object_classes == ("hrcMtaServer",)


def test_mail_transport_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(mail_transport.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("mail_transport") is None


def test_create_server_with_mail_transport_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta1"}},
            "mail_transport": {
                "active": True,
                "values": {
                    "hrcMtaMyHostname": "mta1.example.com",
                    "hrcMtaMyDomain": "example.com",
                    "hrcMtaMyDestinations": ("mta1.example.com, localhost.example.com, localhost"),
                    "hrcMtaHeaderSizeLimit": 102400,
                    "hrcMtaMailboxSizeLimit": 51200000,
                    "hrcMtaMessageSizeLimit": 10485760,
                    "hrcMtaTransportTable": [
                        {
                            "hrcTransportTableMatch": "sub.example.com",
                            "transport": "smtp",
                            "nexthop": "[relay.example.com]:25",
                        }
                    ],
                    "hrcMtaCatchallTable": [
                        {
                            "hrcCatchallTableDomain": "example.com",
                            "hrcCatchallTableRecipient": "postmaster@example.com",
                        }
                    ],
                    "hrcMtaDomainAliasTable": [
                        {
                            "hrcDomainAliasTableFrom": "old-domain.com",
                            "hrcDomainAliasTableTo": "example.com",
                        }
                    ],
                },
            },
        },
    )
    assert dn == f"cn=mta1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcMtaServer" in entry.get("objectClass")
    assert entry.text("hrcMtaMyHostname") == "mta1.example.com"
    assert entry.text("hrcMtaMyDomain") == "example.com"
    assert entry.text("hrcMtaHeaderSizeLimit") == "102400"
    assert entry.text("hrcMtaMailboxSizeLimit") == "51200000"
    assert entry.text("hrcMtaMessageSizeLimit") == "10485760"
    assert entry.texts("hrcMtaTransportTable") == ["sub.example.com;smtp;[relay.example.com]:25"]
    assert entry.texts("hrcMtaCatchallTable") == ["example.com;postmaster@example.com"]
    assert entry.texts("hrcMtaDomainAliasTable") == ["old-domain.com;example.com"]

    loaded = service.load("server", dn)
    assert loaded.tabs["mail_transport"].active is True
    vals = loaded.tabs["mail_transport"].values
    assert vals["hrcMtaMyHostname"] == "mta1.example.com"
    assert vals["hrcMtaHeaderSizeLimit"] == 102400
    assert vals["hrcMtaTransportTable"] == [
        {
            "hrcTransportTableMatch": "sub.example.com",
            "transport": "smtp",
            "nexthop": "[relay.example.com]:25",
        }
    ]
    assert vals["hrcMtaCatchallTable"] == [
        {
            "hrcCatchallTableDomain": "example.com",
            "hrcCatchallTableRecipient": "postmaster@example.com",
        }
    ]
    assert vals["hrcMtaDomainAliasTable"] == [
        {
            "hrcDomainAliasTableFrom": "old-domain.com",
            "hrcDomainAliasTableTo": "example.com",
        }
    ]


def test_update_and_deactivate_mail_transport_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta2"}},
            "mail_transport": {
                "active": True,
                "values": {
                    "hrcMtaMyHostname": "mta2.example.com",
                    "hrcMtaHeaderSizeLimit": 10240,
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "mail_transport": {
                "values": {
                    "hrcMtaHeaderSizeLimit": 20480,
                    "hrcMtaMyDomain": "corp.test",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["mail_transport"].values["hrcMtaHeaderSizeLimit"] == 20480
    assert loaded.tabs["mail_transport"].values["hrcMtaMyDomain"] == "corp.test"

    # Deactivate tab
    service.update("server", dn, {"mail_transport": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcMtaServer" not in entry.get("objectClass")
    assert entry.get("hrcMtaMyHostname") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["mail_transport"].active is False


def test_mail_transport_validation(service: ObjectService) -> None:
    # Negative limit fails
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmta"}},
                "mail_transport": {
                    "active": True,
                    "values": {"hrcMtaHeaderSizeLimit": -10},
                },
            },
        )
    assert "hrcMtaHeaderSizeLimit" in str(exc_info.value)


def test_mail_servers_helper_mail_transport(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    assert mail_transport.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "other-srv"}}})
    assert mail_transport.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta-srv"}},
            "mail_transport": {"active": True, "values": {"hrcMtaMyHostname": "mta.test"}},
        },
    )
    assert mail_transport.mail_servers(directory) == ["mta-srv"]
