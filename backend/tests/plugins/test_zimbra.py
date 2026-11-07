"""Unit and integration tests for the Zimbra plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.systems as systems
import heracles_plugins.zimbra as zimbra
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"

ZIMBRA_CLASSES = {
    "ieee802Device",
    "device",
    "fdServer",
    "fdZimbraServer",
    "ipHost",
    "fdNetworkInterface",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=ZIMBRA_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status_sys = registry.register_plugin(systems.plugin(), schema_classes)
    assert status_sys.enabled
    status_zimbra = registry.register_plugin(zimbra.plugin(), schema_classes)
    assert status_zimbra.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_zimbra_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("zimbra")
    assert tab is not None
    assert tab.acl_key == "serviceZimbra"
    assert server_info.acl_object(tab) == "server/serviceZimbra"
    assert tab.optional is True
    assert tab.object_classes == ("fdZimbraServer",)


def test_zimbra_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "fdServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(zimbra.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("zimbra") is None


def test_create_server_with_zimbra_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "zimbra1"}},
            "zimbra": {
                "active": True,
                "values": {
                    "fdZimbraServerUri": "https://zimbra.example.com:7071/service/admin/soap",
                    "fdZimbraServerLogin": "zimadmin",
                    "fdZimbraServerPassword": "zimsecretpassword",
                    "fdZimbraServerUserAgent": "Heracles-Zimbra-Client/1.0",
                    "fdZimbraServerCreationType": "create",
                    "fdZimbraServerDeletionType": "maintenance",
                    "fdZimbraServerPasswordSync": True,
                    "fdZimbraServerKeepUnknownAliases": True,
                    "fdZimbraServerIdAttribute": "uid",
                    "zimbraDomain": "example.com",
                    "zimbraDomainCOS": "default",
                },
            },
        },
    )
    assert dn == f"cn=zimbra1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"fdZimbraServer" in entry.get("objectClass")
    assert entry.text("fdZimbraServerUri") == "https://zimbra.example.com:7071/service/admin/soap"
    assert entry.text("fdZimbraServerLogin") == "zimadmin"
    assert entry.text("fdZimbraServerPassword") == "zimsecretpassword"
    assert entry.text("fdZimbraServerUserAgent") == "Heracles-Zimbra-Client/1.0"
    assert entry.text("fdZimbraServerCreationType") == "create"
    assert entry.text("fdZimbraServerDeletionType") == "maintenance"
    assert entry.text("fdZimbraServerPasswordSync") == "TRUE"
    assert entry.text("fdZimbraServerKeepUnknownAliases") == "TRUE"
    assert entry.text("fdZimbraServerIdAttribute") == "uid"
    assert entry.text("zimbraDomain") == "example.com"
    assert entry.text("zimbraDomainCOS") == "default"

    loaded = service.load("server", dn)
    assert loaded.tabs["zimbra"].active is True
    vals = loaded.tabs["zimbra"].values
    assert vals["fdZimbraServerUri"] == "https://zimbra.example.com:7071/service/admin/soap"
    assert vals["fdZimbraServerLogin"] == "zimadmin"
    assert vals["fdZimbraServerPassword"] is None  # PasswordAttr is write_only
    assert vals["fdZimbraServerPasswordSync"] is True
    assert vals["fdZimbraServerKeepUnknownAliases"] is True
    assert vals["zimbraDomain"] == "example.com"


def test_update_and_deactivate_zimbra_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "zimbra2"}},
            "zimbra": {
                "active": True,
                "values": {
                    "fdZimbraServerUri": "https://zimbra2.example.com:7071/service/admin/soap",
                    "fdZimbraServerCreationType": "create",
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "zimbra": {
                "values": {
                    "fdZimbraServerDeletionType": "close",
                    "zimbraDomain": "corp.test",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["zimbra"].values["fdZimbraServerDeletionType"] == "close"
    assert loaded.tabs["zimbra"].values["zimbraDomain"] == "corp.test"

    # Deactivate tab
    service.update("server", dn, {"zimbra": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"fdZimbraServer" not in entry.get("objectClass")
    assert entry.get("fdZimbraServerUri") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["zimbra"].active is False


def test_zimbra_validation(service: ObjectService) -> None:
    # Invalid URL
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badzimbra"}},
                "zimbra": {
                    "active": True,
                    "values": {"fdZimbraServerUri": "not-a-valid-url"},
                },
            },
        )
    assert "fdZimbraServerUri" in str(exc_info.value)


def test_mail_servers_helper_zimbra(service: ObjectService, directory: MemoryDirectory) -> None:
    assert zimbra.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "file-srv"}}})
    assert zimbra.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "zimbra-srv"}},
            "zimbra": {
                "active": True,
                "values": {"fdZimbraServerUri": "https://zimbra.test:7071/service/admin/soap"},
            },
        },
    )
    assert zimbra.mail_servers(directory) == ["zimbra-srv"]
