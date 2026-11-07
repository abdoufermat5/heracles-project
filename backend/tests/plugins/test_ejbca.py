"""Tests for the EJBCA plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.ejbca as ejbca
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
CERTS_OU = f"ou=certificates,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(
        d.schema_object_classes() | {"fdejbcacertificate", "fdejbcacertificates"}
    )
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    p = ejbca.plugin()
    status = registry.register_plugin(p, classes)
    assert status.enabled
    return ObjectService(directory, registry)


def test_schema_optional_tab_dropped() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    p = ejbca.plugin()
    registry.register_plugin(p, {"inetorgperson"})
    info = registry.get("user")
    assert info.tab("ejbca") is None


def test_create_ejbca_certificate(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "ejbca_certificate",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "vpn-user-cert",
                    "description": "VPN client certificate profile",
                    "certificateProfile": "ClientCertificate",
                    "endEntityProfile": "VPNUsers",
                }
            }
        },
    )
    assert dn == f"cn=vpn-user-cert,{CERTS_OU}"
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("fdEjbcaCertificate")
    assert entry.text("cn") == "vpn-user-cert"
    assert entry.text("description") == "VPN client certificate profile"
    assert entry.text("certificateProfile") == "ClientCertificate"
    assert entry.text("endEntityProfile") == "VPNUsers"


def test_user_with_ejbca_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    # 1. Create a certificate profile entry
    cert_dn = service.create(
        "ejbca_certificate",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "web-cert",
                    "certificateProfile": "WebClient",
                    "description": "Standard web access",
                }
            }
        },
    )

    # 2. Create user referencing this certificate
    user_dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "alice", "sn": "Smith", "givenName": "Alice"}},
            "ejbca": {
                "active": True,
                "values": {
                    "fdEjbcaCertDN": [cert_dn],
                },
            },
        },
    )
    entry = directory.get(user_dn)
    assert entry is not None
    assert entry.has_object_class("fdEjbcaCertificates")
    assert entry.texts("fdEjbcaCertDN") == [cert_dn]

    # 3. Load user and verify summary
    loaded = service.load("user", user_dn)
    tab = loaded.tabs["ejbca"]
    assert tab.active is True
    summary = tab.values["ejbcaSummary"]
    assert summary is not None
    assert "web-cert" in summary
    assert "WebClient" in summary


def test_deactivate_ejbca_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    cert_dn = service.create(
        "ejbca_certificate",
        BASE,
        {"main": {"values": {"cn": "test-cert"}}},
    )
    user_dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "bob", "sn": "Builder", "givenName": "Bob"}},
            "ejbca": {
                "active": True,
                "values": {"fdEjbcaCertDN": [cert_dn]},
            },
        },
    )
    entry = directory.get(user_dn)
    assert entry is not None
    assert entry.has_object_class("fdEjbcaCertificates")

    service.update("user", user_dn, {"ejbca": {"active": False}})
    entry = directory.get(user_dn)
    assert entry is not None
    assert not entry.has_object_class("fdEjbcaCertificates")
    assert not entry.get("fdEjbcaCertDN")
