"""Password methods: known vectors (generated with openssl / hashlib / bcrypt)."""

from __future__ import annotations

import pytest

from heracles.auth.passwords import (
    EMPTY_LOCK,
    PasswordPolicy,
    PasswordPolicyError,
    UnsupportedOperationError,
    default_registry,
    is_locked,
    lock,
    unlock,
)

REG = default_registry()

# (method id, stored value for the password "secret")
VECTORS: list[tuple[str, str]] = [
    ("clear", "secret"),
    ("clear", "{CLEAR}secret"),
    ("crypt/standard-des", "{CRYPT}abNANd1rDfiNc"),
    ("crypt/md5", "{CRYPT}$1$abcdefgh$cHJi5PXp/ki/ktXzqlk6I1"),
    ("crypt/sha-256", "{CRYPT}$5$abcdefgh$gruCpC7VkOTspMQTTSAR8mtlO9Upms.fwqE5y16JVM."),
    (
        "crypt/sha-512",
        "{CRYPT}$6$abcdefgh$ltjgWl6579NluT/Vi1nwEvcil.G5Nbc4NiXZaNGStk8PSwGfQv72N2CKPPrVACtLtip"
        "/cZ/1GM/O6IND4WQhG.",
    ),
    ("crypt/blowfish", "{CRYPT}$2b$04$RWQxnlDbiguMwLvgCdCHheUyotpZOSb5M/t2QdjCDd1xEiqJMhURO"),
    ("md5", "{MD5}Xr4ilOzQ4PCOq3aQ0qbuaQ=="),
    ("smd5", "{SMD5}VAfQ6nCkaw9o3u+x706wnXNhbHRzYWx0"),
    ("sha", "{SHA}5en6G6MezRroT3XKqkdPOmY/BfQ="),
    ("ssha", "{SSHA}1G904nLkTkGWjKNnQuB/hpWXC/hzYWx0c2FsdA=="),
    (
        "ssha512",
        "{SSHA512}aCu7JRc+kLsuEmFs1zTY+AiP7DSGnjjG+dH28Dp+E5usqoAixeTPihKqZmkWal4mUfp63tqvCAkFV1LK"
        "TDFH6XNhbHRzYWx0",
    ),
]


@pytest.mark.parametrize(("method_id", "stored"), VECTORS)
def test_known_vectors(method_id: str, stored: str) -> None:
    method = REG.detect(stored)
    assert method is not None
    assert method.id == method_id
    assert method.verify("secret", stored)
    assert not method.verify("Secret", stored)
    assert REG.verify("secret", stored)
    assert not REG.verify("wrong", stored)


def test_argon2_vector() -> None:
    stored = REG.hash("secret", "argon2")
    assert stored.startswith("{ARGON2}$argon2id$")
    assert REG.detect(stored) is not None
    assert REG.verify("secret", stored)
    assert not REG.verify("nope", stored)


@pytest.mark.parametrize(
    "method_id",
    [
        "clear",
        "crypt/md5",
        "crypt/sha-256",
        "crypt/sha-512",
        "crypt/blowfish",
        "md5",
        "smd5",
        "sha",
        "ssha",
        "ssha512",
        "argon2",
    ],
)
def test_roundtrip(method_id: str) -> None:
    method = REG.get(method_id)
    stored = method.hash("pässw0rd !")
    assert method.matches(stored)
    assert REG.detect(stored) is method
    assert method.verify("pässw0rd !", stored)
    assert not method.verify("pässw0rd", stored)


def test_salted_methods_use_random_salts() -> None:
    m = REG.get("ssha")
    assert m.hash("x") != m.hash("x")


def test_verify_only_and_special_methods() -> None:
    with pytest.raises(UnsupportedOperationError):
        REG.get("crypt/standard-des").hash("x")
    with pytest.raises(UnsupportedOperationError):
        REG.get("sasl").hash("x")
    sasl = REG.detect("{SASL}jdoe@EXAMPLE.COM")
    assert sasl is not None
    assert sasl.id == "sasl"
    assert not REG.verify("x", "{SASL}jdoe@EXAMPLE.COM")
    empty = REG.detect("")
    assert empty is not None
    assert empty.id == "empty"
    assert not REG.verify("", "")


def test_empty_password_never_verifies() -> None:
    # ``{CLEAR}`` with nothing after it is an empty clear-text password: it must not
    # accept an empty attempt (nor any other scheme's hash of the empty string).
    assert not REG.verify("", "{CLEAR}")
    assert not REG.verify("", REG.hash("", "ssha"))
    assert not REG.verify("", "{MD5}1B2M2Y8AsgTpgAmY7PhCfg==")


@pytest.mark.parametrize("stored", ["{SSHA}!!!", "{SSHA}", "{MD5}@@", "{CRYPT}$6$bad", "{ARGON2}x"])
def test_malformed_values_do_not_verify(stored: str) -> None:
    assert not REG.verify("secret", stored)


def test_lock_helpers() -> None:
    stored = "{SSHA}1G904nLkTkGWjKNnQuB/hpWXC/hzYWx0c2FsdA=="
    locked = lock(stored)
    assert locked == "{SSHA}!1G904nLkTkGWjKNnQuB/hpWXC/hzYWx0c2FsdA=="
    assert is_locked(locked)
    assert not is_locked(stored)
    assert lock(locked) == locked
    assert unlock(locked) == stored
    assert unlock(stored) == stored
    # a locked value never verifies, but its scheme is still detected
    assert not REG.verify("secret", locked)
    method = REG.detect(locked)
    assert method is not None
    assert method.id == "ssha"


def test_lock_empty_password_sentinel() -> None:
    assert lock("") == EMPTY_LOCK == "{CRYPT}!"
    assert is_locked(EMPTY_LOCK)
    assert unlock(EMPTY_LOCK) == ""


def test_lock_clear_text() -> None:
    locked = lock("secret")
    assert is_locked(locked)
    assert unlock(locked) == "{CLEAR}secret"
    assert REG.get("clear").verify("secret", unlock(locked))


def test_policy_length_and_difference() -> None:
    policy = PasswordPolicy(min_length=8, min_differing=3)
    assert policy.problems("short") != []
    assert policy.problems("longenough1") == []
    assert policy.problems("abcdefgh1", previous="abcdefgh2") != []
    assert policy.problems("zzzzabcdefgh", previous="abcdefgh") == []
    with pytest.raises(PasswordPolicyError) as exc:
        policy.validate("abc")
    assert exc.value.problems


def test_policy_method_selection() -> None:
    ssha512 = REG.hash("x", "ssha512")
    keep = PasswordPolicy(default_method="ssha", force_default=False)
    assert keep.method_for(ssha512) == "ssha512"
    assert keep.method_for(None) == "ssha"
    assert keep.method_for("secret") == "ssha"  # clear text not in allowed methods
    forced = PasswordPolicy(default_method="argon2", force_default=True)
    assert forced.method_for(ssha512) == "argon2"
    stored = forced.hash_new("longenough1", current_stored=ssha512)
    assert stored.startswith("{ARGON2}")
