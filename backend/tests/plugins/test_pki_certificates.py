"""PKI plugin: read-only view of PKI-published certificates and user references."""

from __future__ import annotations

import pytest

import heracles_plugins.pki_certificates as pki_certificates
from heracles.ldap.client import Scope
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from tests.plugins.test_certificates import generate_self_signed_cert

BASE = "dc=test"
CERTS = f"ou=certificates,{BASE}"
PEOPLE = f"ou=people,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for ou in ("certificates", "people"):
        d.add(f"ou={ou},{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.set_schema_object_classes([*d.schema_object_classes(), "hrcPkiCertificates"])
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        pki_certificates.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def publish(directory: MemoryDirectory, cn: str) -> str:
    """What the PKI publisher does: an entry carrying userCertificate;binary."""
    der, _pem = generate_self_signed_cert(cn)
    dn = f"cn={cn},{CERTS}"
    directory.add(
        dn,
        {
            "objectClass": [b"inetOrgPerson"],
            "cn": [cn.encode()],
            "sn": [b"x"],
            pki_certificates.CERT_ATTR: [der],
        },
    )
    return dn


def test_published_certificates_are_listed_and_described(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = publish(directory, "vpn-alice")
    page = service.list("pki_certificate", BASE, scope=Scope.SUBTREE)
    assert [r.dn for r in page.items] == [dn]
    values = service.load("pki_certificate", dn).tabs["main"].values
    assert values["cn"] == "vpn-alice"
    assert "CN=vpn-alice" in values["certificateSummary"]


def test_certificates_cannot_be_created_here(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.create("pki_certificate", BASE, {"main": {"values": {"cn": "nope"}}})
    assert "main.cn" in exc.value.fields


def test_user_references_and_summary(service: ObjectService, directory: MemoryDirectory) -> None:
    cert = publish(directory, "vpn-bob")
    user = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "bob", "givenName": "Bob", "sn": "B"}},
            "pki_certificates": {"active": True, "values": {"hrcPkiCertDN": [cert]}},
        },
    )
    entry = directory.get(user)
    assert entry is not None and entry.has_object_class("hrcPkiCertificates")
    assert entry.texts("hrcPkiCertDN") == [cert]
    summary = service.load("user", user).tabs["pki_certificates"].values["pkiSummary"]
    assert summary.startswith("vpn-bob: Subject:")


def test_acl_keys_and_attachment_to_systems() -> None:
    plugin = pki_certificates.plugin()
    assert {a.type_name for a in plugin.tabs} == set(pki_certificates.REFERENCING_TYPES)
    registry = TypeRegistry()
    register_builtin_types(registry)
    registry.register_plugin(plugin, {"hrcpkicertificates"})
    info = registry.get("pki_certificate")
    assert info.acl_object(info.main_tab) == "pkiCertificate/pkiCertificate"
    user = registry.get("user")
    tab = user.tab("pki_certificates")
    assert tab is not None and user.acl_object(tab) == "user/pkiCertificates"


def test_plugin_disabled_without_schema() -> None:
    registry = TypeRegistry()
    assert not registry.register_plugin(pki_certificates.plugin(), {"inetorgperson"}).enabled
