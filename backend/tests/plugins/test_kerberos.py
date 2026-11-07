"""Tests for the Kerberos plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.kerberos as kerberos
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.kerberos import KerberosSettings

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(
        d.schema_object_classes() | {"krbprincipalaux", "krbticketpolicyaux"}
    )
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    p = kerberos.plugin()
    status = registry.register_plugin(p, classes)
    assert status.enabled
    return ObjectService(directory, registry)


def test_plugin_schema_requirement() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    p = kerberos.plugin()
    # Without krbPrincipalAux in schema, the optional tab is dropped
    registry.register_plugin(p, {"inetorgperson"})
    info = registry.get("user")
    assert info.tab("kerberos") is None

    # With krbPrincipalAux and krbTicketPolicyAux, the tab is attached
    registry2 = TypeRegistry()
    register_builtin_types(registry2)
    registry2.register_plugin(p, {"inetorgperson", "krbprincipalaux", "krbticketpolicyaux"})
    info2 = registry2.get("user")
    assert info2.tab("kerberos") is not None


def test_create_user_with_kerberos(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "jdoe",
                    "sn": "Doe",
                    "givenName": "John",
                }
            },
            "kerberos": {
                "active": True,
                "values": {
                    "krbPrincipalName": "jdoe@EXAMPLE.COM",
                    "krbCanonicalName": "jdoe@EXAMPLE.COM",
                    "krbUPEnabled": True,
                    "krbPrincipalExpiration": "2026-12-31",
                    "DISALLOW_FORWARDABLE": True,
                    "REQUIRES_PRE_AUTH": True,
                    "krbAllowedToDelegateTo": ["host/server.example.com"],
                },
            },
        },
    )
    assert dn == f"uid=jdoe,{PEOPLE}"
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("krbPrincipalAux")
    assert entry.has_object_class("krbTicketPolicyAux")
    assert entry.text("krbPrincipalName") == "jdoe@EXAMPLE.COM"
    assert entry.text("krbCanonicalName") == "jdoe@EXAMPLE.COM"
    assert entry.text("krbUPEnabled") == "1"
    assert entry.text("krbPrincipalExpiration") == "20261231000000Z"
    # Bitmask: DISALLOW_FORWARDABLE (0x02) | REQUIRES_PRE_AUTH (0x80) = 0x82 (130)
    assert entry.text("krbTicketFlags") == "130"
    assert entry.texts("krbAllowedToDelegateTo") == ["host/server.example.com"]


def test_on_load_unpacks_ticket_flags(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = f"uid=alice,{PEOPLE}"
    directory.add(
        dn,
        {
            "objectClass": [
                b"top",
                b"person",
                b"organizationalPerson",
                b"inetOrgPerson",
                b"krbPrincipalAux",
                b"krbTicketPolicyAux",
            ],
            "uid": [b"alice"],
            "sn": [b"Smith"],
            "cn": [b"Alice Smith"],
            "krbPrincipalName": [b"alice@EXAMPLE.COM"],
            "krbTicketFlags": [b"130"],  # 0x02 | 0x80
            "krbUPEnabled": [b"1"],
            "krbLoginFailedCount": [b"3"],
            "krbLastAdminUnlock": [b"20260101120000Z"],
        },
    )

    loaded = service.load("user", dn)
    assert "kerberos" in loaded.tabs
    krb_tab = loaded.tabs["kerberos"]
    assert krb_tab.active is True
    krb_vals = krb_tab.values
    assert krb_vals["krbPrincipalName"] == "alice@EXAMPLE.COM"
    assert krb_vals["DISALLOW_FORWARDABLE"] is True
    assert krb_vals["REQUIRES_PRE_AUTH"] is True
    assert krb_vals["DISALLOW_POSTDATED"] is False
    assert krb_vals["krbUPEnabled"] is True
    assert krb_vals["krbLoginFailedCount"] == 3
    assert krb_vals["krbLastAdminUnlock"] is not None


def test_prepare_auto_derives_realm(service: ObjectService, directory: MemoryDirectory) -> None:
    service.registry.settings["kerberos"] = KerberosSettings(default_realm="TEST.REALM")
    dn = service.create(
        "user",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "bob",
                    "sn": "Builder",
                    "givenName": "Bob",
                }
            },
            "kerberos": {
                "active": True,
                "values": {
                    "DISALLOW_TGT_BASED": True,
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("krbPrincipalName") == "bob@TEST.REALM"
    assert entry.text("krbTicketFlags") == "4"


def test_update_ticket_flags(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "carol", "sn": "Carol", "givenName": "C"}},
            "kerberos": {
                "active": True,
                "values": {
                    "krbPrincipalName": "carol@EXAMPLE.COM",
                    "DISALLOW_POSTDATED": True,
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("krbTicketFlags") == "1"

    service.update(
        "user",
        dn,
        {
            "kerberos": {
                "values": {
                    "DISALLOW_POSTDATED": False,
                    "NEW_PRINC": True,
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    # NEW_PRINC is 0x8000 = 32768
    assert entry.text("krbTicketFlags") == "32768"


def test_deactivate_kerberos_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "dave", "sn": "Dave", "givenName": "D"}},
            "kerberos": {
                "active": True,
                "values": {
                    "krbPrincipalName": "dave@EXAMPLE.COM",
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("krbPrincipalAux")

    # Deactivate tab
    service.update("user", dn, {"kerberos": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("krbPrincipalAux")
    assert not entry.has_object_class("krbTicketPolicyAux")
    assert entry.first("krbPrincipalName") is None
