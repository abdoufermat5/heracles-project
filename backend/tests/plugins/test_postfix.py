"""Unit and integration tests for the Postfix plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.postfix as postfix
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
    "hrcPostfixServer",
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
    status_postfix = registry.register_plugin(postfix.plugin(), schema_classes)
    assert status_postfix.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_postfix_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("postfix")
    assert tab is not None
    assert tab.acl_key == "servicePostfix"
    assert server_info.acl_object(tab) == "server/servicePostfix"
    assert tab.optional is True
    assert tab.object_classes == ("hrcPostfixServer",)


def test_postfix_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(postfix.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("postfix") is None


def test_create_server_with_postfix_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta1"}},
            "postfix": {
                "active": True,
                "values": {
                    "hrcPostfixMyHostname": "mta1.example.com",
                    "hrcPostfixMyDomain": "example.com",
                    "hrcPostfixMyDestinations": (
                        "mta1.example.com, localhost.example.com, localhost"
                    ),
                    "hrcPostfixHeaderSizeLimit": 102400,
                    "hrcPostfixMailboxSizeLimit": 51200000,
                    "hrcPostfixMessageSizeLimit": 10485760,
                    "hrcPostfixTransportTable": [
                        {
                            "hrcTransportTableMatch": "sub.example.com",
                            "transport": "smtp",
                            "nexthop": "[relay.example.com]:25",
                        }
                    ],
                    "hrcPostfixCatchallTable": [
                        {
                            "hrcCatchallTableDomain": "example.com",
                            "hrcCatchallTableRecipient": "postmaster@example.com",
                        }
                    ],
                    "hrcPostfixDomainAliasTable": [
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
    assert b"hrcPostfixServer" in entry.get("objectClass")
    assert entry.text("hrcPostfixMyHostname") == "mta1.example.com"
    assert entry.text("hrcPostfixMyDomain") == "example.com"
    assert entry.text("hrcPostfixHeaderSizeLimit") == "102400"
    assert entry.text("hrcPostfixMailboxSizeLimit") == "51200000"
    assert entry.text("hrcPostfixMessageSizeLimit") == "10485760"
    assert entry.texts("hrcPostfixTransportTable") == [
        "sub.example.com;smtp;[relay.example.com]:25"
    ]
    assert entry.texts("hrcPostfixCatchallTable") == ["example.com;postmaster@example.com"]
    assert entry.texts("hrcPostfixDomainAliasTable") == ["old-domain.com;example.com"]

    loaded = service.load("server", dn)
    assert loaded.tabs["postfix"].active is True
    vals = loaded.tabs["postfix"].values
    assert vals["hrcPostfixMyHostname"] == "mta1.example.com"
    assert vals["hrcPostfixHeaderSizeLimit"] == 102400
    assert vals["hrcPostfixTransportTable"] == [
        {
            "hrcTransportTableMatch": "sub.example.com",
            "transport": "smtp",
            "nexthop": "[relay.example.com]:25",
        }
    ]
    assert vals["hrcPostfixCatchallTable"] == [
        {
            "hrcCatchallTableDomain": "example.com",
            "hrcCatchallTableRecipient": "postmaster@example.com",
        }
    ]
    assert vals["hrcPostfixDomainAliasTable"] == [
        {
            "hrcDomainAliasTableFrom": "old-domain.com",
            "hrcDomainAliasTableTo": "example.com",
        }
    ]


def test_update_and_deactivate_postfix_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta2"}},
            "postfix": {
                "active": True,
                "values": {
                    "hrcPostfixMyHostname": "mta2.example.com",
                    "hrcPostfixHeaderSizeLimit": 10240,
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "postfix": {
                "values": {
                    "hrcPostfixHeaderSizeLimit": 20480,
                    "hrcPostfixMyDomain": "corp.test",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["postfix"].values["hrcPostfixHeaderSizeLimit"] == 20480
    assert loaded.tabs["postfix"].values["hrcPostfixMyDomain"] == "corp.test"

    # Deactivate tab
    service.update("server", dn, {"postfix": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcPostfixServer" not in entry.get("objectClass")
    assert entry.get("hrcPostfixMyHostname") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["postfix"].active is False


def test_postfix_validation(service: ObjectService) -> None:
    # Negative limit fails
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badmta"}},
                "postfix": {
                    "active": True,
                    "values": {"hrcPostfixHeaderSizeLimit": -10},
                },
            },
        )
    assert "hrcPostfixHeaderSizeLimit" in str(exc_info.value)


def test_mail_servers_helper_postfix(service: ObjectService, directory: MemoryDirectory) -> None:
    assert postfix.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "other-srv"}}})
    assert postfix.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta-srv"}},
            "postfix": {"active": True, "values": {"hrcPostfixMyHostname": "mta.test"}},
        },
    )
    assert postfix.mail_servers(directory) == ["mta-srv"]
