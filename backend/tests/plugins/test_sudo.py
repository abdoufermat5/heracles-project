"""Sudo plugin: role storage, syntax validation, options catalog, defaults role."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.sudo as sudo
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.sudo.options import OPTION_TYPES, OPTIONS, parse_option
from heracles_plugins.sudo.syntax import command_error, host_error, user_error

BASE = "dc=test"
SUDOERS = f"ou=sudoers,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(SUDOERS, {"objectClass": [b"organizationalUnit"], "ou": [b"sudoers"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        sudo.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def create(service: ObjectService, main: dict[str, Any], options: list[str] | None = None) -> str:
    tabs: dict[str, Any] = {"main": {"values": main}}
    if options is not None:
        tabs["options"] = {"values": {"sudoOption": options}}
    return service.create("sudo", BASE, tabs)


def errors_of(
    service: ObjectService, main: dict[str, Any], options: list[str] | None = None
) -> Any:
    with pytest.raises(ObjectValidationError) as info:
        create(service, main, options)
    return info.value.fields


# ---------------------------------------------------------------- storage


def test_create_stores_exact_values(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create(
        service,
        {
            "cn": "web-admins",
            "description": "Web team",
            "sudoUser": ["alice", "%webteam", "!mallory", "%#1200", "#1001", "+ops"],
            "sudoHost": ["web1.example.org", "10.0.0.0/24"],
            "sudoCommand": ["/usr/bin/systemctl restart nginx", "!/bin/su", "ALL"],
            "sudoRunAsUser": ["root"],
            "sudoRunAsGroup": ["wheel"],
            "sudoOrder": 10,
            "sudoNotBefore": "2030-01-01T00:00:00Z",
            "sudoNotAfter": "2031-01-01T00:00:00Z",
        },
        ["env_reset", "!authenticate", "timestamp_timeout=5", "env_keep+=SSH_AUTH_SOCK"],
    )
    assert dn == f"cn=web-admins,{SUDOERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert [v.decode() for v in entry.get("objectClass")] == ["sudoRole"]
    assert entry.texts("sudoUser") == ["alice", "%webteam", "!mallory", "%#1200", "#1001", "+ops"]
    assert entry.texts("sudoHost") == ["web1.example.org", "10.0.0.0/24"]
    assert entry.texts("sudoCommand") == ["/usr/bin/systemctl restart nginx", "!/bin/su", "ALL"]
    assert entry.texts("sudoRunAsUser") == ["root"]
    assert entry.texts("sudoRunAsGroup") == ["wheel"]
    assert entry.text("sudoOrder") == "10"
    assert entry.text("sudoNotBefore") == "20300101000000Z"
    assert entry.text("sudoNotAfter") == "20310101000000Z"
    assert entry.texts("sudoOption") == [
        "env_reset",
        "!authenticate",
        "timestamp_timeout=5",
        "env_keep+=SSH_AUTH_SOCK",
    ]
    assert entry.get("is_default") == []


def test_sudo_host_defaults_to_all(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create(service, {"cn": "anyhost", "sudoUser": ["bob"], "sudoCommand": ["ALL"]})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.texts("sudoHost") == ["ALL"]


@pytest.mark.parametrize("bad", ["a b", "a,b", "%", "%%grp", "#abc", "+", "!!bob", "bo b"])
def test_invalid_sudo_user_rejected(service: ObjectService, bad: str) -> None:
    errors = errors_of(service, {"cn": "r", "sudoUser": ["alice", bad]})
    assert "main.sudoUser" in errors


@pytest.mark.parametrize("bad", ["not a host", "1.2.3.4/99", "!!ALL"])
def test_invalid_sudo_host_rejected(service: ObjectService, bad: str) -> None:
    assert "main.sudoHost" in errors_of(service, {"cn": "r", "sudoHost": [bad]})


def test_invalid_sudo_command_rejected(service: ObjectService) -> None:
    assert "main.sudoCommand" in errors_of(service, {"cn": "r", "sudoCommand": ["ls -l"]})


def test_invalid_cn_rejected(service: ObjectService) -> None:
    assert "main.cn" in errors_of(service, {"cn": "has space"})
    assert "main.cn" in errors_of(service, {"cn": "a,b"})


def test_negative_priority_rejected(service: ObjectService) -> None:
    assert "main.sudoOrder" in errors_of(service, {"cn": "r", "sudoOrder": -1})


# ------------------------------------------------------------ syntax rules


def test_syntax_helpers() -> None:
    for ok in ("ALL", "root", "!root", "%wheel", "%#10", "#0", "+admins", "svc$", "j.doe@corp"):
        assert user_error(ok) is None, ok
    for ok in ("ALL", "web*", "192.168.1.5", "10.0.0.0/8", "10.0.0.0/255.0.0.0", "::1", "!db1"):
        assert host_error(ok) is None, ok
    for ok in ("ALL", "!ALL", "/bin/ls", "/bin/ls -l /tmp/*", "sudoedit /etc/hosts", "NETCMDS"):
        assert command_error(ok) is None, ok
    assert command_error("ls") is not None
    assert command_error("") is not None
    assert command_error("/bin/ls\nALL") is not None


# ----------------------------------------------------------------- dates


def test_not_after_must_follow_not_before(service: ObjectService) -> None:
    errors = errors_of(
        service,
        {
            "cn": "r",
            "sudoNotBefore": "2030-01-02T00:00:00Z",
            "sudoNotAfter": "2030-01-01T00:00:00Z",
        },
    )
    assert "main.sudoNotAfter" in errors
    same = errors_of(
        service,
        {
            "cn": "r",
            "sudoNotBefore": "2030-01-01T00:00:00Z",
            "sudoNotAfter": "2030-01-01T00:00:00Z",
        },
    )
    assert "main.sudoNotAfter" in same


def test_single_date_is_fine(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create(service, {"cn": "r", "sudoNotAfter": "2030-01-01T00:00:00Z"})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("sudoNotAfter") == "20300101000000Z"


# --------------------------------------------------------------- options


def test_catalog_is_consistent() -> None:
    assert len(OPTIONS) >= 50
    for name, spec in OPTIONS.items():
        assert spec.name == name
        assert spec.type in OPTION_TYPES
        assert spec.description
    for needed in (
        "env_reset",
        "env_keep",
        "secure_path",
        "requiretty",
        "use_pty",
        "timestamp_timeout",
        "badpass_message",
        "visiblepw",
        "umask",
        "fqdn",
    ):
        assert needed in OPTIONS


def test_option_rules() -> None:
    assert parse_option("env_reset").negated is False
    assert parse_option("!env_reset").negated is True
    assert parse_option("passwd_tries=3").value == "3"
    assert parse_option("timestamp_timeout=-1").value == "-1"
    assert parse_option("secure_path=/usr/bin:/bin").value == "/usr/bin:/bin"
    assert parse_option("!secure_path").negated is True
    assert parse_option("!env_keep").negated is True
    assert parse_option("env_keep-=HOME").operator == "-="
    for bad in (
        "frobnicate",
        "env_reset=1",
        "!env_reset=1",
        "passwd_tries",
        "passwd_tries=",
        "passwd_tries=three",
        "!passwd_tries=3",
        "secure_path+=/bin",
        "",
        "=x",
    ):
        with pytest.raises(ValueError):
            parse_option(bad)


@pytest.mark.parametrize(
    "bad", ["frobnicate", "env_reset=yes", "passwd_tries", "umask=abc", "secure_path+=/x"]
)
def test_invalid_options_rejected_by_service(service: ObjectService, bad: str) -> None:
    errors = errors_of(service, {"cn": "r"}, ["env_reset", bad])
    assert "options.sudoOption" in errors


# -------------------------------------------------------------- defaults


def test_is_default_forces_defaults_name(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = create(service, {"cn": "whatever", "is_default": True}, ["env_reset", "!lecture"])
    assert dn == f"cn=defaults,{SUDOERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("cn") == "defaults"
    assert entry.texts("sudoHost") == ["ALL"]
    assert entry.get("sudoUser") == []
    assert entry.get("sudoCommand") == []
    state = service.load("sudo", dn)
    assert state.tabs["main"].values["is_default"] is True


def test_is_default_without_cn_and_load_false_for_others(service: ObjectService) -> None:
    dn = create(service, {"is_default": True})
    assert service.load("sudo", dn).tabs["main"].values["is_default"] is True
    other = create(service, {"cn": "plain", "sudoCommand": ["ALL"]})
    assert service.load("sudo", other).tabs["main"].values["is_default"] is False


def test_named_defaults_reads_back_as_default(service: ObjectService) -> None:
    dn = create(service, {"cn": "defaults"})
    assert service.load("sudo", dn).tabs["main"].values["is_default"] is True


# ------------------------------------------------------ listing and search


def test_listing_and_search(service: ObjectService) -> None:
    create(service, {"cn": "alpha", "description": "first", "sudoUser": ["alice"]})
    create(service, {"cn": "beta", "sudoUser": ["%ops"], "sudoHost": ["db1"]})
    page = service.list("sudo", BASE)
    assert [r.values["cn"] for r in page.items] == ["alpha", "beta"]
    row = {r.values["cn"]: r.values for r in page.items}
    assert row["alpha"]["sudoUser"] == "alice"
    assert row["alpha"]["sudoHost"] == "ALL"
    assert row["alpha"]["description"] == "first"
    assert row["beta"]["sudoHost"] == "db1"
    assert [r.values["cn"] for r in service.list("sudo", BASE, query="ops").items] == ["beta"]
    assert [r.values["cn"] for r in service.list("sudo", BASE, query="first").items] == ["alpha"]
    assert [r.values["cn"] for r in service.list("sudo", BASE, query="db1").items] == ["beta"]


def test_acl_keys_and_category() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    registry.register_plugin(sudo.plugin(), {"sudorole"})
    info = registry.get("sudo")
    assert info.type.category == "access"
    assert info.type.acl_category == "sudo"
    assert [t.acl_key for t in info.tabs] == ["sudo", "sudoOption"]
