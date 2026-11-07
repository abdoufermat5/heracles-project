"""SSH plugin: key parsing, fingerprints, validation, tab rules and lock hook."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import heracles_plugins.posix as posix
import heracles_plugins.ssh as ssh
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.ssh import (
    disable_key,
    enable_key,
    lock_keys,
    md5_fingerprint,
    parse_key,
)

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"

# Key generated beforehand; also the fallback when ssh-keygen is unavailable.
ED_LINE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEN4afpmpx6UcN3RZPI3PaZEelen0CCXeFfX96TNN8Fw fixture"
ED_FP = "5f:d3:2c:e0:1a:21:65:76:3e:2f:d2:17:54:36:ec:e5"
HAS_KEYGEN = shutil.which("ssh-keygen") is not None


def _keygen(tmp_path: Path, args: list[str], name: str) -> tuple[str, str]:
    path = tmp_path / name
    subprocess.run(
        ["ssh-keygen", *args, "-N", "", "-q", "-C", "me@host", "-f", str(path)],
        check=True,
        capture_output=True,
    )
    pub = Path(f"{path}.pub")
    line = pub.read_text().strip()
    out = subprocess.run(
        ["ssh-keygen", "-l", "-E", "md5", "-f", str(pub)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[1]
    return line, out.removeprefix("MD5:")


@pytest.fixture
def real_keys(tmp_path: Path) -> list[tuple[str, str]]:
    if not HAS_KEYGEN:
        return [(ED_LINE, ED_FP)]
    return [
        _keygen(tmp_path, ["-t", "ed25519"], "k_ed"),
        _keygen(tmp_path, ["-t", "rsa", "-b", "2048"], "k_rsa"),
        _keygen(tmp_path, ["-t", "ecdsa"], "k_ec"),
    ]


def test_fingerprint_matches_ssh_keygen(real_keys: list[tuple[str, str]]) -> None:
    for line, expected in real_keys:
        key = parse_key(line)
        assert key is not None
        assert key.fingerprint == expected
        assert key.comment in ("me@host", "fixture")
        assert not key.disabled


def test_fixture_fingerprint() -> None:
    key = parse_key(ED_LINE)
    assert key is not None
    assert key.fingerprint == ED_FP


def test_md5_fingerprint_format() -> None:
    assert md5_fingerprint(b"") == "d4:1d:8c:d9:8f:00:b2:04:e9:80:09:98:ec:f8:42:7e"


def test_parse_variants(real_keys: list[tuple[str, str]]) -> None:
    line, fp = real_keys[0]
    kind, blob = line.split()[:2]
    key = parse_key(f'command="echo hi there",no-pty,from="10.0.0.*" {kind} {blob}')
    assert key is not None
    assert key.fingerprint == fp
    assert key.comment == ""
    dis = parse_key(f"disabled-{kind} {blob} a comment with spaces")
    assert dis is not None
    assert dis.disabled
    assert dis.key_type == kind
    assert dis.comment == "a comment with spaces"
    both = parse_key(f"no-pty disabled-{kind} {blob}")
    assert both is not None
    assert both.disabled


def test_all_accepted_types() -> None:
    blob = "AAAAC3NzaC1lZDI1NTE5AAAAIEN4afpmpx6UcN3RZPI3PaZEelen0CCXeFfX96TNN8Fw"
    for kind in (
        "ssh-rsa",
        "ssh-dss",
        "ssh-ed25519",
        "ecdsa-sha2-nistp384",
        "ecdsa-sk",
        "ed25519-sk",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    ):
        assert parse_key(f"{kind} {blob}") is not None, kind


@pytest.mark.parametrize(
    "line",
    [
        "",
        "ssh-rsa",
        "ssh-rsa not*base64!",
        "ssh-rsa AAAA=BBB",
        "ssh-foo AAAAC3NzaC1lZDI1NTE5",
        "ecdsa-sha2-nistp25 AAAAC3NzaC1lZDI1NTE5",
        "AAAAC3NzaC1lZDI1NTE5",
        "ssh-rsa AAAAC3NzaC1lZDI1NTE5A",
    ],
)
def test_invalid_lines(line: str) -> None:
    assert parse_key(line) is None


def test_disable_enable_idempotent() -> None:
    line = f'from="a b",no-pty {ED_LINE}'
    off = disable_key(line)
    assert off == f'from="a b",no-pty disabled-{ED_LINE}'
    assert disable_key(off) == off
    assert enable_key(off) == line
    assert enable_key(line) == line
    assert disable_key("garbage") == "garbage"
    assert disable_key(f"  {ED_LINE}") == f"disabled-{ED_LINE}"


def test_lock_keys_modification() -> None:
    entry = Entry("uid=x,dc=test", {"sshPublicKey": [ED_LINE.encode()]})
    (mod,) = lock_keys(entry, True)
    assert mod.attr == "sshPublicKey"
    assert list(mod.values) == [f"disabled-{ED_LINE}".encode()]
    locked = Entry("uid=x,dc=test", {"sshPublicKey": list(mod.values)})
    assert lock_keys(locked, True) == []
    (back,) = lock_keys(locked, False)
    assert list(back.values) == [ED_LINE.encode()]
    assert lock_keys(Entry("uid=x,dc=test", {}), True) == []


# ------------------------------------------------------------- ObjectService


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(GROUPS, {"objectClass": [b"organizationalUnit"], "ou": [b"groups"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    for plugin in (posix.plugin(), ssh.plugin()):
        assert registry.register_plugin(plugin, classes).enabled
    return ObjectService(directory, registry)


def create(service: ObjectService, tabs: dict[str, object]) -> str:
    main: dict[str, object] = {"main": {"values": {"uid": "jdoe", "givenName": "J", "sn": "Doe"}}}
    return service.create("user", BASE, {**main, **tabs})


def stored(directory: MemoryDirectory, dn: str) -> Entry:
    entry = directory.get(dn)
    assert entry is not None
    return entry


def test_activation_with_posix(
    service: ObjectService, directory: MemoryDirectory, real_keys: list[tuple[str, str]]
) -> None:
    lines = [line for line, _fp in real_keys]
    dn = create(
        service,
        {
            "posix": {"active": True, "values": {}},
            "ssh": {"active": True, "values": {"sshPublicKey": lines}},
        },
    )
    entry = stored(directory, dn)
    assert entry.has_object_class("ldapPublicKey")
    assert entry.texts("sshPublicKey") == lines
    assert entry.get("keySummary") == []
    tab = service.load("user", dn).tabs["ssh"]
    assert tab.active
    assert real_keys[0][1] in str(tab.values["keySummary"])


def test_activation_without_posix_is_refused(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create(service, {"ssh": {"active": True, "values": {"sshPublicKey": [ED_LINE]}}})
    assert "ssh" in exc.value.fields


def test_invalid_key_is_a_field_error(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create(
            service,
            {
                "posix": {"active": True, "values": {}},
                "ssh": {"active": True, "values": {"sshPublicKey": [ED_LINE, "ssh-rsa !!!"]}},
            },
        )
    assert "Key 2" in exc.value.fields["ssh.sshPublicKey"]


def test_duplicate_fingerprint_is_refused(service: ObjectService) -> None:
    kind, blob = ED_LINE.split()[:2]
    other = f"no-pty disabled-{kind} {blob} other"
    with pytest.raises(ObjectValidationError) as exc:
        create(
            service,
            {
                "posix": {"active": True, "values": {}},
                "ssh": {"active": True, "values": {"sshPublicKey": [ED_LINE, other]}},
            },
        )
    assert ED_FP in exc.value.fields["ssh.sshPublicKey"]


def test_deactivation_removes_keys(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create(
        service,
        {
            "posix": {"active": True, "values": {}},
            "ssh": {"active": True, "values": {"sshPublicKey": [ED_LINE]}},
        },
    )
    service.update("user", dn, {"ssh": {"active": False}})
    entry = stored(directory, dn)
    assert not entry.has_object_class("ldapPublicKey")
    assert entry.texts("sshPublicKey") == []
    assert entry.has_object_class("posixAccount")
