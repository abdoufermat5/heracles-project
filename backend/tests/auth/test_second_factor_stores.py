"""Behaviour shared by every second-factor store (in-memory and SQLite)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pyotp
import pytest

from heracles.auth.second_factor import (
    InMemorySecondFactorStore,
    SecondFactorService,
    SecondFactorStore,
    WebAuthnCredential,
)
from heracles.auth.second_factor_db import SqliteSecondFactorStore
from heracles.storage import Database

DN = "uid=jdoe,ou=people,dc=example,dc=com"
SAME_DN = "UID=jdoe, ou=People,dc=example,dc=com"


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SecondFactorStore]:
    if request.param == "memory":
        yield InMemorySecondFactorStore()
    else:
        db = Database(tmp_path / "h.db")
        yield SqliteSecondFactorStore(db)
        db.close()


def test_totp_secret_and_step(store: SecondFactorStore) -> None:
    assert store.totp_secret(DN) is None
    assert store.last_totp_step(DN) == 0
    store.set_totp_secret(DN, "SECRET")
    store.set_last_totp_step(SAME_DN, 42)
    assert store.totp_secret(SAME_DN) == "SECRET"
    assert store.last_totp_step(DN) == 42
    store.set_totp_secret(DN, None)
    assert store.totp_secret(DN) is None
    assert store.last_totp_step(DN) == 42  # kept: an old code stays unusable


def test_recovery_hashes(store: SecondFactorStore) -> None:
    store.set_recovery_hashes(DN, ["a", "b", "c"])
    assert store.recovery_hashes(SAME_DN) == ["a", "b", "c"]
    assert store.consume_recovery_hash(DN, "b") is True
    assert store.consume_recovery_hash(DN, "b") is False
    assert store.recovery_hashes(DN) == ["a", "c"]
    store.set_recovery_hashes(DN, ["z"])
    assert store.recovery_hashes(DN) == ["z"]


def test_webauthn_credentials(store: SecondFactorStore) -> None:
    store.add_webauthn_credential(DN, WebAuthnCredential(b"k1", b"pk1", 0, "Desk"))
    store.add_webauthn_credential(DN, WebAuthnCredential(b"k2", b"pk2", 3, ""))
    store.update_sign_count(SAME_DN, b"k1", 7)
    creds = store.webauthn_credentials(DN)
    assert creds == [
        WebAuthnCredential(b"k1", b"pk1", 7, "Desk"),
        WebAuthnCredential(b"k2", b"pk2", 3, ""),
    ]
    assert store.webauthn_credentials("uid=other,dc=example,dc=com") == []
    assert store.remove_webauthn_credential(DN, b"k1") is True
    assert store.remove_webauthn_credential(DN, b"k1") is False
    assert [c.credential_id for c in store.webauthn_credentials(DN)] == [b"k2"]


def test_clear_all(store: SecondFactorStore) -> None:
    store.set_totp_secret(DN, "S")
    store.set_recovery_hashes(DN, ["a"])
    store.add_webauthn_credential(DN, WebAuthnCredential(b"k", b"pk", 0))
    store.add_webauthn_credential("uid=other,dc=x", WebAuthnCredential(b"k", b"pk", 0))
    store.clear_all(SAME_DN)
    assert store.totp_secret(DN) is None
    assert store.recovery_hashes(DN) == []
    assert store.webauthn_credentials(DN) == []
    assert len(store.webauthn_credentials("uid=other,dc=x")) == 1


def test_service_on_store(store: SecondFactorStore) -> None:
    svc = SecondFactorService(store)
    store.set_totp_secret(DN, "JBSWY3DPEHPK3PXP")
    store.add_webauthn_credential(DN, WebAuthnCredential(b"k", b"pk", 0))
    store.set_recovery_hashes(DN, ["h"])
    assert svc.methods_for(DN) == ["totp", "webauthn", "recovery"]


def test_totp_step_is_accepted_once(store: SecondFactorStore) -> None:
    secret = "JBSWY3DPEHPK3PXP"
    store.set_totp_secret(DN, secret)
    now = 1_800_000_000.0
    service = SecondFactorService(store, clock=lambda: now)
    code = pyotp.TOTP(secret).at(int(now))
    assert service.verify_totp(SAME_DN, code) is True
    assert service.verify_totp(DN, code) is False  # replayed: the step is gone
    assert store.consume_totp_step(DN, int(now // 30)) is False
    assert service.verify_totp(DN, pyotp.TOTP(secret).at(int(now) + 30)) is True


def test_only_one_request_consumes_a_totp_step(store: SecondFactorStore) -> None:
    """The compare-and-set is atomic, so two requests with one code cannot both pass."""
    store.set_totp_secret(DN, "JBSWY3DPEHPK3PXP")
    step = 60_000_000
    barrier = threading.Barrier(8)
    results: list[bool] = []
    lock = threading.Lock()

    def take() -> None:
        barrier.wait()
        accepted = store.consume_totp_step(DN, step)
        with lock:
            results.append(accepted)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1


def test_sqlite_store_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    db = Database(path)
    first = SqliteSecondFactorStore(db)
    first.set_totp_secret(DN, "S")
    first.add_webauthn_credential(DN, WebAuthnCredential(b"k", b"pk", 1, "Key"))
    first.set_recovery_hashes(DN, ["a", "b"])
    db.close()

    again = SqliteSecondFactorStore(Database(path))
    assert again.totp_secret(DN) == "S"
    assert again.webauthn_credentials(DN) == [WebAuthnCredential(b"k", b"pk", 1, "Key")]
    assert again.recovery_hashes(DN) == ["a", "b"]
