"""Unit and integration tests for the Sieve plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.sieve as sieve
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"

SIEVE_CLASSES = {
    "ieee802Device",
    "device",
    "hrcServer",
    "hrcSieveServer",
    "ipHost",
    "hrcNetworkInterface",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=SIEVE_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status_sys = registry.register_plugin(systems.plugin(), schema_classes)
    assert status_sys.enabled
    status_sieve = registry.register_plugin(sieve.plugin(), schema_classes)
    assert status_sieve.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_sieve_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("sieve")
    assert tab is not None
    assert tab.acl_key == "serviceSieve"
    assert server_info.acl_object(tab) == "server/serviceSieve"
    assert tab.optional is True
    assert tab.object_classes == ("hrcSieveServer",)


def test_sieve_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(sieve.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("sieve") is None


def test_create_server_with_sieve_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "sieve1"}},
            "sieve": {
                "active": True,
                "values": {
                    "hrcSieveConnectURL": "sieve.example.com",
                    "hrcSieveConnectPort": 4190,
                    "hrcSieveConnectOptions": "/tls",
                    "hrcSieveAdmin": "sieveadmin",
                    "hrcSievePassword": "sievepassword",
                },
            },
        },
    )
    assert dn == f"cn=sieve1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcSieveServer" in entry.get("objectClass")
    assert entry.text("hrcSieveConnectURL") == "sieve.example.com"
    assert entry.text("hrcSieveConnectPort") == "4190"
    assert entry.text("hrcSieveConnectOptions") == "/tls"
    assert entry.text("hrcSieveAdmin") == "sieveadmin"
    assert entry.text("hrcSievePassword") == "sievepassword"

    loaded = service.load("server", dn)
    assert loaded.tabs["sieve"].active is True
    vals = loaded.tabs["sieve"].values
    assert vals["hrcSieveConnectURL"] == "sieve.example.com"
    assert vals["hrcSieveConnectPort"] == 4190
    assert vals["hrcSieveConnectOptions"] == "/tls"
    assert vals["hrcSieveAdmin"] == "sieveadmin"
    assert vals["hrcSievePassword"] is None  # write-only: never sent back


def test_update_and_deactivate_sieve_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "sieve2"}},
            "sieve": {
                "active": True,
                "values": {
                    "hrcSieveConnectURL": "sieve2.example.com",
                    "hrcSieveConnectPort": 4190,
                    "hrcSieveConnectOptions": "/notls",
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "sieve": {
                "values": {
                    "hrcSieveConnectPort": 2000,
                    "hrcSieveConnectOptions": "/ssl",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["sieve"].values["hrcSieveConnectPort"] == 2000
    assert loaded.tabs["sieve"].values["hrcSieveConnectOptions"] == "/ssl"

    # Deactivate tab
    service.update("server", dn, {"sieve": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcSieveServer" not in entry.get("objectClass")
    assert entry.get("hrcSieveConnectURL") == []
    assert entry.get("hrcSieveConnectPort") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["sieve"].active is False


def test_sieve_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badsieve"}},
                "sieve": {
                    "active": True,
                    "values": {"hrcSieveConnectPort": 70000},
                },
            },
        )
    assert "hrcSieveConnectPort" in str(exc_info.value)


def test_mail_servers_helper_sieve(service: ObjectService, directory: MemoryDirectory) -> None:
    assert sieve.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "app-srv"}}})
    assert sieve.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "sieve-srv"}},
            "sieve": {"active": True, "values": {"hrcSieveConnectURL": "sieve.test"}},
        },
    )
    assert sieve.mail_servers(directory) == ["sieve-srv"]


def test_admin_password_is_write_only_and_kept_when_empty(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "sieve-pw"}},
            "sieve": {"active": True, "values": {"hrcSievePassword": "first-secret"}},
        },
    )
    assert service.load("server", dn).tabs["sieve"].values["hrcSievePassword"] is None
    assert (directory.get(dn) or pytest.fail()).text("hrcSievePassword") == "first-secret"

    service.update("server", dn, {"sieve": {"values": {"hrcSievePassword": ""}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcSievePassword") == "first-secret"

    service.update("server", dn, {"sieve": {"values": {"hrcSievePassword": "second-secret"}}})
    assert (directory.get(dn) or pytest.fail()).text("hrcSievePassword") == "second-secret"
