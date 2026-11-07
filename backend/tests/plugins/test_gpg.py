"""Tests for the GPG plugin."""

from __future__ import annotations

import base64
import struct

import pytest

import heracles_plugins.gpg as gpg
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.gpg.parser import parse_openpgp_key

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
PGP_OU = f"ou=pgp,{BASE}"
CONFIGS_OU = f"ou=configs,{BASE}"


def make_dummy_armored_key(user_id: str = "Alice <alice@example.com>") -> str:
    # Public Key packet (tag 6): version 4, ts=1700000000, algo 1 (RSA), dummy MPIs
    key_body = struct.pack(">B I B H 2s H 2s", 4, 1700000000, 1, 16, b"\x12\x34", 16, b"\x01\x00")
    key_packet = b"\x99" + struct.pack(">H", len(key_body)) + key_body
    # User ID packet (tag 13 in old format: 0x80 | (13 << 2) | 0 = 0xB4)
    uid_bytes = user_id.encode("utf-8")
    uid_packet = bytes([0xB4, len(uid_bytes)]) + uid_bytes

    payload = base64.b64encode(key_packet + uid_packet).decode("ascii")
    return (
        "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
        "Version: Heracles PGP\n\n"
        f"{payload}\n"
        "=abcd\n"
        "-----END PGP PUBLIC KEY BLOCK-----\n"
    )


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(
        d.schema_object_classes() | {"fdgpgaccount", "pgpkeyinfo", "pgpserverinfo"}
    )
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(PGP_OU, {"objectClass": [b"organizationalUnit"], "ou": [b"pgp"]})
    d.add(CONFIGS_OU, {"objectClass": [b"organizationalUnit"], "ou": [b"configs"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    p = gpg.plugin()
    status = registry.register_plugin(p, classes)
    assert status.enabled
    return ObjectService(directory, registry)


def test_parser_with_hex_fingerprint() -> None:
    fp = "A1B2 C3D4 E5F6 0123 4567 89AB CDEF 0123 4567 89AB"
    parsed = parse_openpgp_key(fp)
    assert parsed is not None
    assert parsed.fingerprint == "A1B2C3D4E5F60123456789ABCDEF0123456789AB"
    assert parsed.cert_id == "CDEF0123456789AB"


def test_parser_with_hex_key_id() -> None:
    key_id = "1234567890ABCDEF"
    parsed = parse_openpgp_key(key_id)
    assert parsed is not None
    assert parsed.cert_id == "1234567890ABCDEF"
    assert parsed.fingerprint == "1234567890ABCDEF"


def test_parser_with_armored_block() -> None:
    armored = make_dummy_armored_key("Bob Smith <bob@example.com>")
    parsed = parse_openpgp_key(armored)
    assert parsed is not None
    assert len(parsed.fingerprint) == 40
    assert len(parsed.cert_id) == 16
    assert parsed.user_id == "Bob Smith <bob@example.com>"
    assert parsed.key_type == "RSA"
    assert parsed.created_at is not None


def test_create_pgp_key(service: ObjectService, directory: MemoryDirectory) -> None:
    armored = make_dummy_armored_key("Alice <alice@example.com>")
    dn = service.create(
        "pgp_key",
        BASE,
        {
            "main": {
                "values": {
                    "pgpKey": armored,
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("pgpKeyInfo")
    assert entry.text("pgpUserID") == "Alice <alice@example.com>"
    cert_id = entry.text("pgpCertID")
    assert cert_id is not None and len(cert_id) == 16
    assert entry.text("pgpKeyType") == "RSA"


def test_create_pgp_server_info(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "pgp_server_info",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "main-pgp",
                    "pgpSoftware": "Heracles Keyserver",
                    "pgpVersion": "1.0",
                    "baseKeyBranchDN": PGP_OU,
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("pgpServerInfo")
    assert entry.text("cn") == "main-pgp"
    assert entry.text("pgpSoftware") == "Heracles Keyserver"
    assert entry.text("baseKeyBranchDN") == PGP_OU


def test_user_gpg_account_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    # 1. Create a PGP key object
    key_dn = service.create(
        "pgp_key",
        BASE,
        {
            "main": {
                "values": {
                    "pgpCertID": "A1B2C3D4E5F67890",
                    "pgpUserID": "John Doe <john@example.com>",
                    "pgpFingerprint": "00112233445566778899AABBCCDDEEFFA1B2C3D4",
                }
            }
        },
    )

    # 2. Create user with gpg tab referencing this key
    user_dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "gpg": {
                "active": True,
                "values": {
                    "fdUserKeyDN": [key_dn],
                },
            },
        },
    )
    entry = directory.get(user_dn)
    assert entry is not None
    assert entry.has_object_class("fdGpgAccount")
    assert entry.texts("fdUserKeyDN") == [key_dn]

    # 3. Load user and check gpgSummary
    loaded = service.load("user", user_dn)
    gpg_tab = loaded.tabs["gpg"]
    assert gpg_tab.active is True
    summary = gpg_tab.values["gpgSummary"]
    assert summary is not None
    assert "A1B2C3D4E5F67890" in summary
    assert "John Doe <john@example.com>" in summary


def test_deactivate_gpg_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    key_dn = service.create(
        "pgp_key",
        BASE,
        {
            "main": {
                "values": {
                    "pgpCertID": "B2C3D4E5F6789012",
                    "pgpUserID": "Dave <dave@example.com>",
                }
            }
        },
    )
    user_dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "dave", "sn": "Dave", "givenName": "Dave"}},
            "gpg": {
                "active": True,
                "values": {
                    "fdUserKeyDN": [key_dn],
                },
            },
        },
    )
    entry = directory.get(user_dn)
    assert entry is not None
    assert entry.has_object_class("fdGpgAccount")

    service.update("user", user_dn, {"gpg": {"active": False}})
    entry = directory.get(user_dn)
    assert entry is not None
    assert not entry.has_object_class("fdGpgAccount")
    assert not entry.get("fdUserKeyDN")
