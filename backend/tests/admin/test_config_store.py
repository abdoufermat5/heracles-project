from __future__ import annotations

import pytest

from heracles.core import config_store as cs
from heracles.ldap.memory import MemoryDirectory
from heracles.schema import names as schema

BASE = "dc=example,dc=test"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"dcObject", b"organization"], "dc": [b"example"]})
    return d


def test_missing_entry_yields_yaml_defaults(directory: MemoryDirectory) -> None:
    cfg = cs.effective_settings(directory)
    assert cfg.login_attribute == "uid"
    assert cfg.password_min_length == 8
    assert cfg.from_directory == frozenset()


def test_save_creates_entry_and_directory_wins(directory: MemoryDirectory) -> None:
    written = cs.save_config(
        directory,
        {"password_min_length": 12, "login_attribute": "mail", "recovery_enabled": True},
    )
    assert set(written) == {"password_min_length", "login_attribute", "recovery_enabled"}
    entry = directory.get(cs.config_dn(directory))
    assert entry is not None
    assert entry.texts("hrcPasswordMinLength") == ["12"]
    assert entry.texts("hrcPasswordRecoveryActivated") == ["TRUE"]
    classes = {c.lower() for c in entry.texts("objectClass")}
    assert schema.OC.RECOVERY_CONFIG.lower() in classes
    cfg = cs.effective_settings(directory)  # cache invalidated by the save
    assert cfg.password_min_length == 12
    assert cfg.login_attribute == "mail"
    assert "password_min_length" in cfg.from_directory


def test_save_writes_only_changes_and_keeps_unknown_attributes(directory: MemoryDirectory) -> None:
    cs.save_config(directory, {"timezone": "Europe/Paris"})
    dn = cs.config_dn(directory)
    from heracles.ldap.client import Modification

    directory.modify(dn, [Modification("add", "description", [b"keep me"])])
    assert cs.save_config(directory, {"timezone": "Europe/Paris"}) == []
    assert cs.save_config(directory, {"timezone": "UTC", "language": "fr"}) == [
        "timezone",
        "language",
    ]
    entry = directory.get(dn)
    assert entry is not None
    assert entry.texts("description") == ["keep me"]


def test_empty_value_removes_attribute(directory: MemoryDirectory) -> None:
    cs.save_config(directory, {"shells": ["/bin/sh", "/bin/zsh"], "cas_host": "cas.example"})
    cs.save_config(directory, {"shells": [], "cas_host": ""})
    entry = directory.get(cs.config_dn(directory))
    assert entry is not None
    assert entry.get("hrcShells") == []
    assert entry.get("hrcCasHost") == []


def test_validation_errors(directory: MemoryDirectory) -> None:
    with pytest.raises(cs.ConfigError) as exc:
        cs.save_config(directory, {"password_min_length": -1, "nope": 1, "language": "xx"})
    assert set(exc.value.fields) == {"password_min_length", "nope", "language"}
    assert directory.get(cs.config_dn(directory)) is None


def test_login_method_inferred_from_flags(directory: MemoryDirectory) -> None:
    cs.save_config(directory, {"http_header_auth_enabled": True, "http_header_name": "X-User"})
    cfg = cs.effective_settings(directory)
    assert cfg.login_method == "http_header"
    assert cfg.http_header_name == "X-User"
    cs.save_config(directory, {"login_method": "form"})
    assert cs.effective_settings(directory).login_method == "form"


def test_stored_boolean_case_and_unparseable_int(directory: MemoryDirectory) -> None:
    cs.save_config(directory, {"timezone": "UTC"})
    from heracles.ldap.client import Modification

    directory.modify(
        cs.config_dn(directory),
        [
            Modification("add", "hrcForceSSL", [b"true"]),
            Modification("add", "hrcMinId", [b"abc"]),
        ],
    )
    cs.invalidate(directory)
    cfg = cs.effective_settings(directory)
    assert cfg.get("force_ssl") is True
    assert cfg.min_id == 0


def test_tab_hooks_roundtrip(directory: MemoryDirectory) -> None:
    hooks = ["user|postcreate|echo hi", "posixAccount|premodify|#false"]
    cs.save_config(directory, {"tab_hooks": hooks, "display_hook_output": True})
    cfg = cs.effective_settings(directory)
    assert sorted(cfg.tab_hooks) == sorted(hooks)
    assert cfg.display_hook_output is True


def test_every_field_has_an_attribute() -> None:
    keys = {f.key for f in cs.CONFIG_FIELDS}
    assert keys <= set(schema.CONFIG_ATTRS)
    assert {f.section for f in cs.CONFIG_FIELDS} <= set(cs.SECTIONS)


def test_a_failed_read_is_retried_soon_and_does_not_stick_for_the_whole_ttl(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heracles.ldap.client import DirectoryUnavailableError

    cs.save_config(directory, {"password_min_length": 14})
    cs.invalidate(directory)
    real_get = directory.get
    clock = [1000.0]
    monkeypatch.setattr(cs.time, "monotonic", lambda: clock[0])

    def down(_dn: str, _attrs: object = None) -> None:
        raise DirectoryUnavailableError("down")

    monkeypatch.setattr(directory, "get", down)
    assert cs.effective_settings(directory).password_min_length == 8  # YAML fallback
    monkeypatch.setattr(directory, "get", real_get)
    clock[0] += cs.FAILURE_TTL_SECONDS + 0.1  # far below the 30 s cache TTL
    assert cs.effective_settings(directory).password_min_length == 14
