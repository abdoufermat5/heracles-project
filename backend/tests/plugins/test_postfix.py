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
    "fdServer",
    "fdPostfixServer",
    "ipHost",
    "fdNetworkInterface",
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
    assert tab.object_classes == ("fdPostfixServer",)


def test_postfix_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "fdServer"])
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
                    "postfixMyHostname": "mta1.example.com",
                    "postfixMyDomain": "example.com",
                    "postfixMyDestinations": "mta1.example.com, localhost.example.com, localhost",
                    "postfixHeaderSizeLimit": 102400,
                    "postfixMailboxSizeLimit": 51200000,
                    "postfixMessageSizeLimit": 10485760,
                    "fdPostfixTransportTable": [
                        {
                            "fdTransportTableMatch": "sub.example.com",
                            "transport": "smtp",
                            "nexthop": "[relay.example.com]:25",
                        }
                    ],
                    "fdPostfixCatchallTable": [
                        {
                            "fdCatchallTableDomain": "example.com",
                            "fdCatchallTableRecipient": "postmaster@example.com",
                        }
                    ],
                    "fdPostfixDomainAliasTable": [
                        {
                            "fdDomainAliasTableFrom": "old-domain.com",
                            "fdDomainAliasTableTo": "example.com",
                        }
                    ],
                },
            },
        },
    )
    assert dn == f"cn=mta1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"fdPostfixServer" in entry.get("objectClass")
    assert entry.text("postfixMyHostname") == "mta1.example.com"
    assert entry.text("postfixMyDomain") == "example.com"
    assert entry.text("postfixHeaderSizeLimit") == "102400"
    assert entry.text("postfixMailboxSizeLimit") == "51200000"
    assert entry.text("postfixMessageSizeLimit") == "10485760"
    assert entry.texts("fdPostfixTransportTable") == ["sub.example.com;smtp;[relay.example.com]:25"]
    assert entry.texts("fdPostfixCatchallTable") == ["example.com;postmaster@example.com"]
    assert entry.texts("fdPostfixDomainAliasTable") == ["old-domain.com;example.com"]

    loaded = service.load("server", dn)
    assert loaded.tabs["postfix"].active is True
    vals = loaded.tabs["postfix"].values
    assert vals["postfixMyHostname"] == "mta1.example.com"
    assert vals["postfixHeaderSizeLimit"] == 102400
    assert vals["fdPostfixTransportTable"] == [
        {
            "fdTransportTableMatch": "sub.example.com",
            "transport": "smtp",
            "nexthop": "[relay.example.com]:25",
        }
    ]
    assert vals["fdPostfixCatchallTable"] == [
        {
            "fdCatchallTableDomain": "example.com",
            "fdCatchallTableRecipient": "postmaster@example.com",
        }
    ]
    assert vals["fdPostfixDomainAliasTable"] == [
        {
            "fdDomainAliasTableFrom": "old-domain.com",
            "fdDomainAliasTableTo": "example.com",
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
                    "postfixMyHostname": "mta2.example.com",
                    "postfixHeaderSizeLimit": 10240,
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
                    "postfixHeaderSizeLimit": 20480,
                    "postfixMyDomain": "corp.test",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["postfix"].values["postfixHeaderSizeLimit"] == 20480
    assert loaded.tabs["postfix"].values["postfixMyDomain"] == "corp.test"

    # Deactivate tab
    service.update("server", dn, {"postfix": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"fdPostfixServer" not in entry.get("objectClass")
    assert entry.get("postfixMyHostname") == []

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
                    "values": {"postfixHeaderSizeLimit": -10},
                },
            },
        )
    assert "postfixHeaderSizeLimit" in str(exc_info.value)


def test_mail_servers_helper_postfix(service: ObjectService, directory: MemoryDirectory) -> None:
    assert postfix.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "other-srv"}}})
    assert postfix.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "mta-srv"}},
            "postfix": {"active": True, "values": {"postfixMyHostname": "mta.test"}},
        },
    )
    assert postfix.mail_servers(directory) == ["mta-srv"]
