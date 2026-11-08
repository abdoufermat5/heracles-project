"""Tests for the certificates plugin."""

from __future__ import annotations

import base64
import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import heracles_plugins.certificates as certs_plugin
from heracles.attributes import ValidationError
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.certificates import (
    CertificateAttr,
    parse_cert,
    summarize_certificates,
    to_der,
)

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"


def generate_self_signed_cert(cn: str = "Test User", org: str = "Heracles") -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COMMON_NAME, cn),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, org),
        ]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return der, pem


@pytest.fixture
def test_cert() -> tuple[bytes, str]:
    return generate_self_signed_cert("Alice", "Acme Corp")


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(d.schema_object_classes() | {"strongauthenticationuser"})
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    p = certs_plugin.plugin()
    status = registry.register_plugin(p, classes)
    assert status.enabled
    return ObjectService(directory, registry)


def test_to_der_and_parse_cert(test_cert: tuple[bytes, str]) -> None:
    der, pem = test_cert

    # From DER
    assert to_der(der) == der
    # From PEM
    assert to_der(pem) == der
    # From base64 DER
    b64_der = base64.b64encode(der).decode("ascii")
    assert to_der(b64_der) == der

    # Parse details
    info = parse_cert(der)
    assert info is not None
    assert "CN=Alice" in info.subject
    assert "O=Acme Corp" in info.issuer
    assert info.not_valid_before < info.not_valid_after
    assert len(info.fingerprint.split(":")) == 32  # SHA-256


def test_certificate_attr_validation() -> None:
    attr = CertificateAttr("cert", "Certificate")
    with pytest.raises(ValidationError):
        attr.from_json("invalid garbage not base64 or pem")


def test_summarize_certificates(test_cert: tuple[bytes, str]) -> None:
    der, _ = test_cert
    summary = summarize_certificates({"userCertificate;binary": [der]})
    assert summary is not None
    assert "CN=Alice" in summary
    assert "Acme Corp" in summary
    assert "SHA-256" in summary


def test_create_user_with_certificate(
    service: ObjectService, directory: MemoryDirectory, test_cert: tuple[bytes, str]
) -> None:
    der, pem = test_cert
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "alice", "sn": "Smith", "givenName": "Alice"}},
            "certificates": {
                "active": True,
                "values": {
                    "userCertificate;binary": [pem],
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("strongAuthenticationUser")
    stored = entry.get("userCertificate;binary")
    assert len(stored) == 1
    assert stored[0] == der

    loaded = service.load("user", dn)
    certs_tab = loaded.tabs["certificates"]
    assert certs_tab.active is True
    assert certs_tab.values["userCertificate;binary"] == [der]
    assert "CN=Alice" in certs_tab.values["certificateSummary"]


def test_pem_import_helper(
    service: ObjectService, directory: MemoryDirectory, test_cert: tuple[bytes, str]
) -> None:
    der, pem = test_cert
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "bob", "sn": "Builder", "givenName": "Bob"}},
            "certificates": {
                "active": True,
                "values": {
                    "pem_import": pem,
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("strongAuthenticationUser")
    assert entry.get("userCertificate;binary") == [der]


def test_fallback_user_certificate(
    service: ObjectService, directory: MemoryDirectory, test_cert: tuple[bytes, str]
) -> None:
    der, _ = test_cert
    dn = f"uid=carol,{PEOPLE}"
    # Stored under "userCertificate" instead of "userCertificate;binary"
    directory.add(
        dn,
        {
            "objectClass": [
                b"top",
                b"person",
                b"organizationalPerson",
                b"inetOrgPerson",
                b"strongAuthenticationUser",
            ],
            "uid": [b"carol"],
            "sn": [b"Carol"],
            "cn": [b"Carol"],
            "userCertificate": [der],
        },
    )

    loaded = service.load("user", dn)
    assert loaded.tabs["certificates"].values["userCertificate;binary"] == [der]


def test_deactivate_certificates_tab(
    service: ObjectService, directory: MemoryDirectory, test_cert: tuple[bytes, str]
) -> None:
    der, _ = test_cert
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "dave", "sn": "Dave", "givenName": "Dave"}},
            "certificates": {
                "active": True,
                "values": {"userCertificate;binary": [der]},
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("strongAuthenticationUser")

    service.update("user", dn, {"certificates": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("strongAuthenticationUser")
    assert not entry.get("userCertificate;binary")
