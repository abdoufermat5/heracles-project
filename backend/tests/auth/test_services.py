"""Unit tests for sessions, login helpers, second factor, mail and WebAuthn plumbing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pyotp
import pytest

from heracles.auth import csrf
from heracles.auth.login import (
    InvalidLoginError,
    LoginConfig,
    authenticate_bind,
    authenticate_header,
    escape_filter_value,
    find_user_dn,
    is_trusted_proxy,
    parse_networks,
)
from heracles.auth.mail import MemoryMailer, SmtpMailer
from heracles.auth.ratelimit import RateLimiter
from heracles.auth.second_factor import InMemorySecondFactorStore, SecondFactorService
from heracles.auth.sessions import InMemorySessionStore
from heracles.auth.webauthn import WebAuthnService, WebAuthnSettings
from tests.auth.fakes import FakeDirectory


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_session_lifecycle_and_expiry() -> None:
    clock = Clock()
    store = InMemorySessionStore(clock=clock)
    s = store.create("uid=a,dc=x", "main")
    assert s.authenticated
    s.cache["acl"] = {"x": 1}
    clock.now += 1799
    got = store.get(s.id)
    assert got is not None
    assert got.cache["acl"] == {"x": 1}
    clock.now += 1801
    assert store.get(s.id) is None


def test_session_absolute_lifetime_and_rotation() -> None:
    clock = Clock()
    store = InMemorySessionStore(clock=clock)
    s = store.create(
        "uid=a,dc=x", "main", second_factor_pending=True, second_factor_methods=["totp"]
    )
    assert not s.authenticated
    old = s.id
    rotated = store.rotate(old)
    assert rotated is not None and rotated.id != old
    assert store.get(old) is None
    assert store.get(rotated.id) is rotated
    for _ in range(26):
        clock.now += 1700
        store.get(rotated.id)
    assert store.get(rotated.id) is None
    assert store.rotate("nope") is None
    assert store.delete("nope") is None


def test_session_delete() -> None:
    store = InMemorySessionStore()
    s = store.create("uid=a,dc=x", "main")
    assert store.delete(s.id) is s
    assert store.get(s.id) is None
    assert len(store) == 0


def test_csrf_check() -> None:
    csrf.check("GET", "/api/v2/x", None, None)
    csrf.check("POST", "/api/v1/login", None, None)
    csrf.check("POST", "/api/v2/x", "abc", "abc")
    with pytest.raises(csrf.CsrfError):
        csrf.check("POST", "/api/v2/x", "abc", "abd")
    with pytest.raises(csrf.CsrfError):
        csrf.check("DELETE", "/api/v2/x", "abc", None)
    with pytest.raises(csrf.CsrfError):
        csrf.check("POST", "/api/v1x/login", None, None)


def test_escape_filter_value() -> None:
    assert escape_filter_value("a*(b)\\c\x00") == "a\\2a\\28b\\29\\5cc\\00"
    assert escape_filter_value("josé") == "jos\\c3\\a9"


def test_find_user_requires_exactly_one_match() -> None:
    d = FakeDirectory()
    d.add_user("a", "pw", mail="shared@example.com")
    d.add_user("b", "pw", mail="shared@example.com")
    by_uid = LoginConfig()
    by_mail = LoginConfig(login_attribute="mail")
    assert find_user_dn(d, by_uid, "a") == "uid=a,ou=people,dc=example,dc=com"
    assert find_user_dn(d, by_uid, "zzz") is None
    assert find_user_dn(d, by_mail, "shared@example.com") is None  # ambiguous
    assert find_user_dn(d, by_uid, "  ") is None
    d.add_user("c", "pw", mail="solo@example.com")
    assert find_user_dn(d, by_mail, "solo@example.com") is not None
    with pytest.raises(InvalidLoginError):
        authenticate_bind(d, by_mail, "shared@example.com", "pw")
    assert authenticate_bind(d, by_mail, "solo@example.com", "pw").startswith("uid=c,")


def test_header_auth_and_trusted_networks() -> None:
    d = FakeDirectory()
    dn = d.add_user("a", "pw")
    nets = parse_networks(["10.0.0.1", "192.168.0.0/16", "::1"])
    assert is_trusted_proxy("10.0.0.1", nets)
    assert is_trusted_proxy("192.168.4.4", nets)
    assert is_trusted_proxy("::1", nets)
    assert not is_trusted_proxy("10.0.0.2", nets)
    assert not is_trusted_proxy("garbage", nets)
    assert not is_trusted_proxy(None, nets)
    cfg = LoginConfig()
    assert authenticate_header(d, cfg, peer_ip="10.0.0.1", trusted=nets, header_value="a") == dn
    with pytest.raises(InvalidLoginError):
        authenticate_header(d, cfg, peer_ip="1.1.1.1", trusted=nets, header_value="a")
    with pytest.raises(InvalidLoginError):
        authenticate_header(d, cfg, peer_ip="10.0.0.1", trusted=nets, header_value=None)
    with pytest.raises(InvalidLoginError):
        authenticate_header(d, cfg, peer_ip="10.0.0.1", trusted=nets, header_value="ghost")


def test_rate_limiter_exponential_backoff() -> None:
    clock = Clock()
    rl = RateLimiter(free_attempts=1, base_delay=1.0, max_delay=5.0, clock=clock)
    key = rl.key("1.2.3.4", " JDoe ")
    assert key == rl.key("1.2.3.4", "jdoe")
    assert rl.retry_after(key) == 0
    rl.record_failure(key)
    assert rl.retry_after(key) == 1.0
    clock.now += 1.0
    rl.record_failure(key)
    assert rl.retry_after(key) == 2.0
    clock.now += 2.0
    rl.record_failure(key)
    assert rl.retry_after(key) == 4.0
    clock.now += 4.0
    rl.record_failure(key)
    assert rl.retry_after(key) == 5.0  # capped
    clock.now += 4000
    assert rl.retry_after(key) == 0  # forgotten
    rl.record_failure(key)
    rl.record_success(key)
    assert rl.retry_after(key) == 0


def test_rate_limiter_table_is_bounded() -> None:
    """Attacker-chosen keys must not grow the table: expired entries go, then the oldest."""
    clock = Clock()
    rl = RateLimiter(free_attempts=0, base_delay=60.0, max_entries=20, clock=clock)
    for i in range(20):
        rl.record_failure(f"k{i}")
        clock.now += 1.0
    assert rl.retry_after("k19") > 0
    for i in range(20, 500):
        rl.record_failure(f"k{i}")
        clock.now += 1.0
        assert len(rl._entries) <= 20  # pyright: ignore[reportPrivateUsage]
    assert rl.retry_after("k499") > 0  # the newest key is kept
    assert rl.retry_after("k0") == 0  # the oldest was evicted
    clock.now += 4000
    rl.record_failure("late")
    assert len(rl._entries) == 1  # pyright: ignore[reportPrivateUsage]


def test_totp_service_window() -> None:
    clock = Clock()
    clock.now = 1_700_000_000.0
    svc = SecondFactorService(InMemorySecondFactorStore(), clock=clock)
    dn = "uid=a,dc=x"
    assert svc.methods_for(dn) == []
    secret, uri = svc.enroll_totp(dn, "a@example.com")
    assert uri.startswith("otpauth://totp/")
    assert svc.methods_for(dn) == ["totp"]
    totp = pyotp.TOTP(secret)
    assert not svc.verify_totp(dn, totp.at(int(clock.now) + 90))
    assert not svc.verify_totp(dn, "abcdef")
    assert svc.verify_totp(dn, totp.at(int(clock.now) + 30))  # +1 step
    assert not svc.verify_totp(dn, totp.at(int(clock.now)))  # older than last used step
    clock.now += 60
    assert svc.verify_totp(dn, totp.at(int(clock.now)))


def test_recovery_codes_hashed_and_single_use() -> None:
    store = InMemorySecondFactorStore()
    svc = SecondFactorService(store)
    dn = "uid=a,dc=x"
    codes = svc.regenerate_recovery_codes(dn, 3)
    assert len(codes) == 3 and all(len(c) == 11 for c in codes)
    assert all(c not in "".join(store.recovery_hashes(dn)) for c in codes)
    assert svc.verify(dn, "recovery", codes[0].lower())
    assert not svc.verify(dn, "recovery", codes[0])
    assert svc.verify(dn, "recovery", codes[1])
    assert not svc.verify(dn, "webauthn", "x")


def test_memory_mailer_and_smtp_mailer() -> None:
    m = MemoryMailer()
    m.send("a@x", "s", "b")
    assert m.outbox[0].to == "a@x"
    with patch("heracles.auth.mail.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        SmtpMailer("mail.local", 587, sender="h@x", username="u", password="p", starttls=True).send(
            "a@x", "Subj", "Body"
        )
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    sent = smtp.send_message.call_args.args[0]
    assert sent["To"] == "a@x" and sent["Subject"] == "Subj"


def test_webauthn_options_generation() -> None:
    store = InMemorySecondFactorStore()
    svc = WebAuthnService(
        store, WebAuthnSettings(rp_id="example.com", origin="https://example.com")
    )
    reg = svc.begin_registration("uid=a,dc=x", "a", "Alice")
    assert reg.options["rp"]["id"] == "example.com"
    assert len(reg.challenge) >= 32
    assert svc.begin_assertion("uid=a,dc=x").options["rpId"] == "example.com"
