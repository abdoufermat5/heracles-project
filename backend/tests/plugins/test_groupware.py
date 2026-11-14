"""Unit and integration tests for the Groupware plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.groupware as groupware
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"

ZIMBRA_CLASSES = {
    "ieee802Device",
    "device",
    "hrcServer",
    "hrcGroupwareServer",
    "ipHost",
    "hrcNetworkInterface",
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
    status_groupware = registry.register_plugin(groupware.plugin(), schema_classes)
    assert status_groupware.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_groupware_tab_registration_and_acl(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    tab = server_info.tab("groupware")
    assert tab is not None
    assert tab.acl_key == "serviceGroupware"
    assert server_info.acl_object(tab) == "server/serviceGroupware"
    assert tab.optional is True
    assert tab.object_classes == ("hrcGroupwareServer",)


def test_groupware_tab_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(["ieee802Device", "device", "hrcServer"])
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(groupware.plugin(), schema_classes)

    server_info = registry.get("server")
    assert server_info.tab("groupware") is None


def test_create_server_with_groupware_service(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "groupware1"}},
            "groupware": {
                "active": True,
                "values": {
                    "hrcGroupwareServerUri": "https://groupware.example.com:7071/service/admin/soap",
                    "hrcGroupwareServerLogin": "zimadmin",
                    "hrcGroupwareServerPassword": "zimsecretpassword",
                    "hrcGroupwareServerUserAgent": "Heracles-Groupware-Client/1.0",
                    "hrcGroupwareServerCreationType": "create",
                    "hrcGroupwareServerDeletionType": "maintenance",
                    "hrcGroupwareServerPasswordSync": True,
                    "hrcGroupwareServerKeepUnknownAliases": True,
                    "hrcGroupwareServerIdAttribute": "uid",
                    "hrcGroupwareDomain": "example.com",
                    "hrcGroupwareDomainServiceClass": "default",
                },
            },
        },
    )
    assert dn == f"cn=groupware1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcGroupwareServer" in entry.get("objectClass")
    assert (
        entry.text("hrcGroupwareServerUri")
        == "https://groupware.example.com:7071/service/admin/soap"
    )
    assert entry.text("hrcGroupwareServerLogin") == "zimadmin"
    assert entry.text("hrcGroupwareServerPassword") == "zimsecretpassword"
    assert entry.text("hrcGroupwareServerUserAgent") == "Heracles-Groupware-Client/1.0"
    assert entry.text("hrcGroupwareServerCreationType") == "create"
    assert entry.text("hrcGroupwareServerDeletionType") == "maintenance"
    assert entry.text("hrcGroupwareServerPasswordSync") == "TRUE"
    assert entry.text("hrcGroupwareServerKeepUnknownAliases") == "TRUE"
    assert entry.text("hrcGroupwareServerIdAttribute") == "uid"
    assert entry.text("hrcGroupwareDomain") == "example.com"
    assert entry.text("hrcGroupwareDomainServiceClass") == "default"

    loaded = service.load("server", dn)
    assert loaded.tabs["groupware"].active is True
    vals = loaded.tabs["groupware"].values
    assert vals["hrcGroupwareServerUri"] == "https://groupware.example.com:7071/service/admin/soap"
    assert vals["hrcGroupwareServerLogin"] == "zimadmin"
    assert vals["hrcGroupwareServerPassword"] is None  # PasswordAttr is write_only
    assert vals["hrcGroupwareServerPasswordSync"] is True
    assert vals["hrcGroupwareServerKeepUnknownAliases"] is True
    assert vals["hrcGroupwareDomain"] == "example.com"


def test_update_and_deactivate_groupware_tab(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "groupware2"}},
            "groupware": {
                "active": True,
                "values": {
                    "hrcGroupwareServerUri": "https://groupware2.example.com:7071/service/admin/soap",
                    "hrcGroupwareServerCreationType": "create",
                },
            },
        },
    )

    # Update attributes
    service.update(
        "server",
        dn,
        {
            "groupware": {
                "values": {
                    "hrcGroupwareServerDeletionType": "close",
                    "hrcGroupwareDomain": "corp.test",
                }
            }
        },
    )
    loaded = service.load("server", dn)
    assert loaded.tabs["groupware"].values["hrcGroupwareServerDeletionType"] == "close"
    assert loaded.tabs["groupware"].values["hrcGroupwareDomain"] == "corp.test"

    # Deactivate tab
    service.update("server", dn, {"groupware": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcGroupwareServer" not in entry.get("objectClass")
    assert entry.get("hrcGroupwareServerUri") == []

    loaded_deactivated = service.load("server", dn)
    assert loaded_deactivated.tabs["groupware"].active is False


def test_groupware_validation(service: ObjectService) -> None:
    # Invalid URL
    with pytest.raises(ObjectValidationError) as exc_info:
        service.create(
            "server",
            BASE,
            {
                "main": {"values": {"cn": "badgroupware"}},
                "groupware": {
                    "active": True,
                    "values": {"hrcGroupwareServerUri": "not-a-valid-url"},
                },
            },
        )
    assert "hrcGroupwareServerUri" in str(exc_info.value)


def test_mail_servers_helper_groupware(service: ObjectService, directory: MemoryDirectory) -> None:
    assert groupware.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "file-srv"}}})
    assert groupware.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "groupware-srv"}},
            "groupware": {
                "active": True,
                "values": {
                    "hrcGroupwareServerUri": "https://groupware.test:7071/service/admin/soap"
                },
            },
        },
    )
    assert groupware.mail_servers(directory) == ["groupware-srv"]
