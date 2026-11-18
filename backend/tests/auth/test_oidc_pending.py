"""Pending OpenID Connect sign-ins: single use, short-lived, in memory or in the database."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from heracles.auth.oidc import (
    MAX_PENDING,
    PENDING_SECONDS,
    MemoryPendingStore,
    OidcSettings,
    Pending,
    PendingStore,
    SqlPendingStore,
    code_challenge,
)
from heracles.storage import Database


def _memory(_: Path) -> PendingStore:
    return MemoryPendingStore()


def _sqlite(tmp: Path) -> PendingStore:
    return SqlPendingStore(Database(tmp / "heracles.db"))


@pytest.fixture(params=[_memory, _sqlite], ids=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> PendingStore:
    factory: Callable[[Path], PendingStore] = request.param
    return factory(tmp_path)


def _pending(state: str, at: float = 1000.0) -> Pending:
    return Pending(state, "nonce", "verifier", "main", "/next", at)


def test_taken_once(store: PendingStore) -> None:
    store.add(_pending("s1"))
    assert store.take("s1", 1001.0) == _pending("s1")
    assert store.take("s1", 1001.0) is None
    assert store.take("unknown", 1001.0) is None


def test_expires(store: PendingStore) -> None:
    store.add(_pending("s1"))
    assert store.take("s1", 1000.0 + PENDING_SECONDS + 1) is None
    # an expired one is swept when a new one arrives
    store.add(_pending("s2", 1000.0))
    store.add(_pending("s3", 1000.0 + PENDING_SECONDS + 5))
    assert store.take("s2", 1000.0) is None
    assert store.take("s3", 1000.0 + PENDING_SECONDS + 6) is not None


def test_pending_rows_are_capped_oldest_first(
    store: PendingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("heracles.auth.oidc.MAX_PENDING", 3)
    assert MAX_PENDING > 3
    for i in range(5):
        store.add(_pending(f"s{i}", 1000.0 + i))
    now = 1010.0
    assert [store.take(f"s{i}", now) is not None for i in range(5)] == [
        False,
        False,
        True,
        True,
        True,
    ]


@pytest.mark.parametrize(
    ("issuer", "insecure", "ok"),
    [
        ("https://idp.example.test", False, True),
        ("http://idp.example.test", False, False),
        ("http://idp.example.test", True, False),
        ("http://localhost:8180/r", False, False),
        ("http://localhost:8180/r", True, True),
        ("http://idp.localhost:8180/r", True, True),
        ("http://127.0.0.1:8180/r", True, True),
        ("ftp://localhost/r", True, False),
    ],
)
def test_issuer_must_be_https_unless_local_development(
    issuer: str, insecure: bool, ok: bool
) -> None:
    def build() -> OidcSettings:
        return OidcSettings(
            enabled=True,
            issuer=issuer,
            client_id="x",
            client_auth="none",
            allow_insecure_http=insecure,
        )

    if ok:
        build()
    else:
        with pytest.raises(ValueError, match="https"):
            build()


def test_pkce_challenge_is_rfc7636_s256() -> None:
    # RFC 7636, appendix B
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_client_secret_from_a_file(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("from-file\n", encoding="utf-8")
    settings = OidcSettings(
        enabled=True,
        issuer="https://idp.example.test",
        client_id="heracles",
        client_secret_file=str(secret),
    )
    assert settings.client_secret == "from-file"
    with pytest.raises(ValueError, match="not both"):
        OidcSettings(client_secret="x", client_secret_file=str(secret))
