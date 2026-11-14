"""Constraints of the configuration knobs: refused on write, tolerated on read."""

from __future__ import annotations

from typing import Any

import pytest

from heracles.auth.passwords import default_registry
from heracles.core import config_store as cs
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory

BASE = "dc=example,dc=test"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"dcObject", b"organization"], "dc": [b"example"]})
    return d


def _refused(directory: MemoryDirectory, changes: dict[str, Any]) -> set[str]:
    with pytest.raises(cs.ConfigError) as exc:
        cs.save_config(directory, changes)
    return set(exc.value.fields)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        # RDNs and DNs
        ("user_rdn", "anything"),
        ("group_rdn", "ou=a,ou=b"),
        ("acl_role_rdn", "=x"),
        ("ogroup_rdn", "ou="),
        ("token_rdn", "nope"),
        ("orchestrator_token_rdn", "nope"),
        ("recovery_token_rdn", "nope"),
        ("tasks_rdn", "nope"),
        ("mail_template_rdn", "nope"),
        ("snapshot_base", "anything"),
        # attribute names
        ("login_attribute", "not an attribute"),
        ("recovery_login_attribute", "1bad name"),
        ("modification_detection_attribute", "a;b c"),
        # paths
        ("default_shell", "bash"),
        ("next_id_hook", "hook.sh"),
        ("cas_ca_cert_path", "ca.pem"),
        ("ssl_ca_cert_path", "relative/ca.pem"),
        ("ssl_key_path", "key.pem"),
        ("ssl_cert_path", "cert.pem"),
        ("shells", ["/bin/sh", "zsh"]),
        ("shells", ["/bin/sh", "/bin/sh"]),
        # hashes
        ("password_default_hash", "foo"),
        ("password_allowed_hashes", ["ssha", "foo"]),
        ("password_allowed_hashes", ["ssha", "ssha"]),
        # numbers
        ("password_min_length", 0),
        ("password_min_length", -3),
        ("password_min_length", "8"),
        ("password_min_length", True),
        ("session_lifetime", 59),
        ("cas_port", 0),
        ("cas_port", 65536),
        ("recovery_validity", 0),
        ("min_id", -1),
        ("min_id", 2**32),
        ("acl_target_filter_limit", 0),
        ("ldap_size_limit", -1),
        ("max_avatar_size", 0),
        ("tasks_max_emails", "ten"),
        ("tasks_interval_emails", -5),
        # text formats
        ("cas_host", "has space"),
        ("timezone", "Mars"),
        ("recovery_email", "not-an-address"),
        ("http_header_name", "bad header"),
        ("mail_domain", "localhost"),
        ("uid_number_base", "abc"),
        ("gid_number_base", "2000-1100"),
        ("uid_number_base", "1100-"),
    ],
)
def test_invalid_value_is_refused_on_its_key(
    directory: MemoryDirectory, key: str, value: Any
) -> None:
    assert _refused(directory, {key: value}) == {key}
    assert directory.get(cs.config_dn(directory)) is None  # nothing was written


@pytest.mark.parametrize(
    "changes",
    [
        {"user_rdn": "ou=staff", "group_rdn": "ou=teams", "acl_role_rdn": "ou=roles"},
        {"snapshot_base": "ou=snapshots,dc=example,dc=test"},
        {"login_attribute": "mail", "recovery_login_attribute": "uid"},
        {"shells": ["/bin/sh", "/usr/bin/fish"], "default_shell": "/usr/bin/fish"},
        {"password_default_hash": "argon2", "password_allowed_hashes": ["argon2", "ssha512"]},
        {"password_min_length": 12, "password_min_differ": 4, "session_lifetime": 60},
        {"cas_host": "cas.example.org", "cas_port": 8443, "timezone": "Europe/Paris"},
        {"recovery_email": "admin@example.org", "http_header_name": "X-Remote-User"},
        {"uid_number_base": "10000-20000", "gid_number_base": "5000"},
        {"tasks_max_emails": 50, "tasks_interval_emails": 300, "ldap_size_limit": 0},
        {"ssl_ca_cert_path": "/etc/ssl/ca.pem", "next_id_hook": "/usr/local/bin/next-id"},
    ],
)
def test_valid_values_are_saved(directory: MemoryDirectory, changes: dict[str, Any]) -> None:
    assert set(cs.save_config(directory, changes)) == set(changes)


def test_empty_values_are_always_allowed(directory: MemoryDirectory) -> None:
    cs.save_config(directory, {"user_rdn": "ou=staff", "cas_port": 8443, "timezone": "UTC"})
    emptied: dict[str, Any] = {
        "user_rdn": "",
        "cas_port": None,
        "timezone": "",
        "shells": [],
        "password_default_hash": "",
    }
    cs.save_config(directory, emptied)
    cfg = cs.effective_settings(directory)
    assert cfg.user_rdn == "ou=people" and cfg.cas_port is None


def test_every_hash_scheme_the_backend_can_produce_is_accepted(
    directory: MemoryDirectory,
) -> None:
    hashable = default_registry().hashable_ids()
    assert list(cs.FIELDS_BY_KEY["password_default_hash"].options) == hashable
    assert list(cs.FIELDS_BY_KEY["password_allowed_hashes"].options) == hashable
    for method in hashable:
        cs.save_config(directory, {"password_default_hash": method})
    cs.save_config(
        directory, {"password_allowed_hashes": hashable, "password_default_hash": "ssha"}
    )


# ----------------------------------------------------------------- cross-field rules


def test_default_shell_must_be_one_of_the_shells(directory: MemoryDirectory) -> None:
    assert _refused(directory, {"default_shell": "/bin/csh"}) == {"default_shell"}
    # the stored default (/bin/bash) is not in the new list: the list is at fault
    assert _refused(directory, {"shells": ["/bin/sh"]}) == {"shells"}
    # both written together: the pair is consistent
    cs.save_config(directory, {"shells": ["/bin/sh"], "default_shell": "/bin/sh"})
    # and the stored default counts when only the list changes
    assert _refused(directory, {"shells": ["/bin/zsh"]}) == {"shells"}
    # both written and inconsistent: reported on the dependent key
    assert _refused(directory, {"shells": ["/bin/zsh"], "default_shell": "/bin/sh"}) == {
        "default_shell"
    }


def test_default_hash_must_be_allowed(directory: MemoryDirectory) -> None:
    assert _refused(
        directory, {"password_allowed_hashes": ["ssha512"], "password_default_hash": "ssha"}
    ) == {"password_default_hash"}
    cs.save_config(directory, {"password_allowed_hashes": ["ssha512", "ssha"]})
    assert _refused(directory, {"password_default_hash": "argon2"}) == {"password_default_hash"}
    assert _refused(directory, {"password_allowed_hashes": ["argon2"]}) == {
        "password_allowed_hashes"
    }
    # an empty allowed list means "no restriction"
    cs.save_config(directory, {"password_allowed_hashes": [], "password_default_hash": "argon2"})


def test_min_differ_cannot_exceed_min_length(directory: MemoryDirectory) -> None:
    assert _refused(directory, {"password_min_differ": 9}) == {"password_min_differ"}
    cs.save_config(directory, {"password_min_length": 10, "password_min_differ": 10})
    assert _refused(directory, {"password_min_length": 6}) == {"password_min_length"}


def test_pool_bounds_are_ordered(directory: MemoryDirectory) -> None:
    assert _refused(directory, {"uid_pool_min": 5000, "uid_pool_max": 4000}) == {"uid_pool_max"}
    cs.save_config(directory, {"gid_pool_min": 2000, "gid_pool_max": 3000})
    assert _refused(directory, {"gid_pool_min": 4000}) == {"gid_pool_min"}
    assert _refused(directory, {"gid_pool_max": 1000}) == {"gid_pool_max"}
    # one bound alone is fine
    cs.save_config(directory, {"uid_pool_min": 100})


def test_id_range_must_end_above_min_id(directory: MemoryDirectory) -> None:
    assert _refused(directory, {"uid_number_base": "1100-1500", "min_id": 1600}) == {
        "uid_number_base"
    }
    cs.save_config(directory, {"uid_number_base": "1100-2000"})
    assert _refused(directory, {"min_id": 2500}) == {"min_id"}
    cs.save_config(directory, {"min_id": 1500})


# ----------------------------------------------------------------- compatibility


def test_stored_garbage_is_still_readable_and_does_not_block_other_saves(
    directory: MemoryDirectory,
) -> None:
    cs.save_config(directory, {"timezone": "UTC"})
    directory.modify(
        cs.config_dn(directory),
        [
            Modification("add", "hrcUserRDN", [b"anything"]),
            Modification("add", "hrcDefaultShell", [b"bash"]),
            Modification("replace", "hrcTimezone", [b"Mars"]),
            Modification("add", "hrcPasswordDefaultHash", [b"foo"]),
            Modification("add", "hrcCasPort", [b"0"]),
        ],
    )
    cs.invalidate(directory)
    cfg = cs.effective_settings(directory)
    assert cfg.user_rdn == "anything"
    assert cfg.default_shell == "bash"
    assert cfg.timezone == "Mars"
    assert cfg.password_default_hash == "foo"
    assert cfg.cas_port == 0
    # an unrelated change goes through: rules only look at the keys being written
    assert cs.save_config(directory, {"password_min_length": 12}) == ["password_min_length"]
    # and the garbage value is refused again as soon as it is written
    assert _refused(directory, {"user_rdn": "anything"}) == {"user_rdn"}


def test_fields_expose_their_constraints() -> None:
    by_key = {f["key"]: f for f in cs.describe_fields()}
    assert by_key["user_rdn"]["constraints"] == {"format": "rdn"}
    assert by_key["cas_port"]["constraints"] == {"min": 1, "max": 65535}
    assert by_key["shells"]["constraints"] == {"item_format": "abs_path", "unique": True}
    assert by_key["password_min_length"]["constraints"]["min"] == 1
    assert by_key["theme"]["constraints"] == {}
    assert by_key["password_default_hash"]["options"] == default_registry().hashable_ids()


@pytest.mark.parametrize(
    ("fmt", "value", "valid"),
    [
        ("email", "admin@example.org", True),
        ("email", "admin@localhost", False),
        ("email", "no at sign", False),
        ("http_header", "X-Remote-User", True),
        ("http_header", "AUTH_USER", True),
        ("http_header", "bad header", False),
        ("http_header", "bad:header", False),
        ("id_range", "1100", True),
        ("id_range", "1100-2000", True),
        ("id_range", "2000-1100", False),
        ("id_range", "1100-1100", False),
        ("id_range", "1100-", False),
        ("id_range", "4294967296", False),
        ("id_range", "abc", False),
    ],
)
def test_added_formats(fmt: str, value: str, valid: bool) -> None:
    from heracles.core.formats import check

    assert (check(fmt, value) is None) is valid
