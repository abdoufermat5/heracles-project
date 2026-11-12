"""Self-service TOTP and recovery-code enrolment through API v2."""

from __future__ import annotations

import pyotp

from heracles.auth.second_factor import (
    TOTP_STEP_SECONDS,
    WebAuthnCredential,
    hash_recovery_code,
)
from tests.api.conftest import Env

BASE = "/api/v2/auth"
TOTP = BASE + "/totp"
CODES = BASE + "/recovery-codes"
SECRET = "JBSWY3DPEHPK3PXP"


def _code(env: Env, secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).at(int(env.clock.now) + offset * TOTP_STEP_SECONDS)


def _delete(env: Env, confirm: bool = False) -> int:
    url = TOTP + ("?confirm_disable=true" if confirm else "")
    return env.client.delete(url, headers=env.headers()).status_code


def _enable(env: Env) -> str:
    """Enrol TOTP through the API; return the secret."""
    begin = env.post(TOTP + "/begin").json()
    assert env.post(TOTP + "/confirm", {"code": _code(env, begin["secret"])}).status_code == 200
    return str(begin["secret"])


def _add_key(env: Env) -> None:
    env.second_factor.add_webauthn_credential(
        env.user_dn, WebAuthnCredential(b"key-1", b"pub", 1, "key")
    )


# -- access control -----------------------------------------------------------------------------
def test_every_endpoint_requires_a_full_login(env: Env) -> None:
    assert env.client.get(TOTP).status_code == 401
    assert env.post(TOTP + "/begin").status_code == 401
    assert env.post(TOTP + "/confirm", {"code": "123456"}).status_code == 401
    assert _delete(env) == 401
    assert env.post(CODES).status_code == 401


def test_pending_second_factor_session_is_refused(env: Env) -> None:
    env.second_factor.set_totp_secret(env.user_dn, SECRET)
    assert env.login().json()["status"] == "second_factor"
    assert env.client.get(TOTP).status_code == 401
    assert env.post(TOTP + "/begin").status_code == 401
    assert env.post(CODES).status_code == 401


def test_changes_need_a_recent_password_but_status_does_not(env: Env) -> None:
    env.login()
    env.clock.advance(301)

    assert env.client.get(TOTP).status_code == 200
    for r in (
        env.post(TOTP + "/begin"),
        env.post(TOTP + "/confirm", {"code": "123456"}),
        env.client.delete(TOTP, headers=env.headers()),
        env.post(CODES),
    ):
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "reauth_required"

    assert env.post(BASE + "/reauth", {"password": "s3cretpass"}).status_code == 200
    assert env.post(TOTP + "/begin").status_code == 200


# -- status -------------------------------------------------------------------------------------
def test_status_reflects_the_account(env: Env) -> None:
    env.login()
    assert env.client.get(TOTP).json() == {
        "enabled": False,
        "recovery_codes_remaining": 0,
        "security_keys": 0,
    }
    _enable(env)
    _add_key(env)
    env.post(CODES)
    assert env.client.get(TOTP).json() == {
        "enabled": True,
        "recovery_codes_remaining": 10,
        "security_keys": 1,
    }


# -- enrolment ----------------------------------------------------------------------------------
def test_begin_does_not_activate_and_confirm_does(env: Env) -> None:
    env.login()
    r = env.post(TOTP + "/begin")
    assert r.status_code == 200
    body = r.json()
    assert body["uri"].startswith("otpauth://totp/")
    assert body["secret"] in body["uri"]
    assert "jdoe" in body["uri"]
    assert body["expires_in"] == 300
    assert env.second_factor.totp_secret(env.user_dn) is None

    ok = env.post(TOTP + "/confirm", {"code": _code(env, body["secret"])})
    assert ok.status_code == 200
    assert env.second_factor.totp_secret(env.user_dn) == body["secret"]
    assert env.client.get(TOTP).json()["enabled"] is True


def test_wrong_code_does_not_activate_and_allows_a_retry(env: Env) -> None:
    env.login()
    secret = env.post(TOTP + "/begin").json()["secret"]
    wrong = str((int(_code(env, secret)) + 1) % 1_000_000).zfill(6)
    r = env.post(TOTP + "/confirm", {"code": wrong})
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"code": "Wrong code"}
    assert env.second_factor.totp_secret(env.user_dn) is None
    assert env.post(TOTP + "/confirm", {"code": "abcdef"}).status_code == 422

    assert env.post(TOTP + "/confirm", {"code": _code(env, secret)}).status_code == 200
    assert env.second_factor.totp_secret(env.user_dn) == secret


def test_confirm_without_begin_is_refused(env: Env) -> None:
    env.login()
    assert env.post(TOTP + "/confirm", {"code": "123456"}).status_code == 422
    assert env.second_factor.totp_secret(env.user_dn) is None


def test_pending_secret_expires(env: Env) -> None:
    env.login()
    secret = env.post(TOTP + "/begin").json()["secret"]
    code = _code(env, secret)
    env.clock.advance(301)
    env.post(BASE + "/reauth", {"password": "s3cretpass"})
    assert env.post(TOTP + "/confirm", {"code": _code(env, secret)}).status_code == 422
    assert env.second_factor.totp_secret(env.user_dn) is None
    # the expired secret is gone for good, even for a code that would have matched earlier
    env.clock.now -= 301
    assert env.post(TOTP + "/confirm", {"code": code}).status_code == 422


def test_pending_secret_is_single_use_and_replaced_by_a_new_begin(env: Env) -> None:
    env.login()
    first = env.post(TOTP + "/begin").json()["secret"]
    second = env.post(TOTP + "/begin").json()["secret"]
    assert first != second
    assert env.post(TOTP + "/confirm", {"code": _code(env, first)}).status_code == 422
    # the failed confirm kept the pending secret for a retry with the right code
    assert env.post(TOTP + "/confirm", {"code": _code(env, second)}).status_code == 200
    assert env.post(TOTP + "/confirm", {"code": _code(env, second)}).status_code == 422


def test_pending_secret_belongs_to_the_session(env: Env) -> None:
    env.login()
    secret = env.post(TOTP + "/begin").json()["secret"]
    env.client.cookies.clear()
    env.csrf_token = str(env.client.get(BASE + "/csrf").json()["token"])
    env.login()
    assert env.post(TOTP + "/confirm", {"code": _code(env, secret)}).status_code == 422


def test_enrolled_totp_is_required_at_the_next_login(env: Env) -> None:
    env.login()
    secret = _enable(env)
    env.client.cookies.clear()
    env.csrf_token = str(env.client.get(BASE + "/csrf").json()["token"])
    assert env.login().json() == {"status": "second_factor", "methods": ["totp"]}

    env.clock.advance(TOTP_STEP_SECONDS * 2)
    ok = env.post(BASE + "/second-factor", {"method": "totp", "code": _code(env, secret)})
    assert ok.status_code == 200
    assert env.client.get(BASE + "/me").status_code == 200


def test_confirmation_code_cannot_be_replayed_at_login(env: Env) -> None:
    env.login()
    secret = _enable(env)
    code = _code(env, secret)
    env.client.cookies.clear()
    env.csrf_token = str(env.client.get(BASE + "/csrf").json()["token"])
    env.login()
    r = env.post(BASE + "/second-factor", {"method": "totp", "code": code})
    assert r.status_code == 401


def test_reenrolling_replaces_the_secret(env: Env) -> None:
    env.login()
    old = _enable(env)
    env.clock.advance(TOTP_STEP_SECONDS * 2)
    new = env.post(TOTP + "/begin").json()["secret"]
    assert env.second_factor.totp_secret(env.user_dn) == old  # still the old one until confirmed
    assert env.post(TOTP + "/confirm", {"code": _code(env, new)}).status_code == 200
    assert env.second_factor.totp_secret(env.user_dn) == new


# -- disabling ----------------------------------------------------------------------------------
def test_disabling_the_only_factor_needs_confirmation(env: Env) -> None:
    env.login()
    _enable(env)
    env.post(CODES)
    r = env.client.delete(TOTP, headers=env.headers())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_second_factor"
    assert env.second_factor.totp_secret(env.user_dn) is not None

    assert _delete(env, confirm=True) == 204
    assert env.second_factor.totp_secret(env.user_dn) is None
    assert env.second_factor.recovery_hashes(env.user_dn) == []  # nothing left to recover from
    assert env.client.get(TOTP).json()["enabled"] is False
    assert _delete(env, confirm=True) == 404


def test_disabling_totp_keeps_recovery_codes_when_a_key_remains(env: Env) -> None:
    env.login()
    _enable(env)
    _add_key(env)
    env.post(CODES)
    assert _delete(env) == 204
    assert env.second_factor.totp_secret(env.user_dn) is None
    assert len(env.second_factor.recovery_hashes(env.user_dn)) == 10
    assert env.client.get(TOTP).json()["recovery_codes_remaining"] == 10


def test_disabling_without_totp_is_404(env: Env) -> None:
    env.login()
    assert _delete(env) == 404


def test_disabling_cancels_a_pending_enrolment(env: Env) -> None:
    env.login()
    secret = _enable(env)
    env.clock.advance(TOTP_STEP_SECONDS * 2)
    pending = env.post(TOTP + "/begin").json()["secret"]
    assert _delete(env, confirm=True) == 204
    assert env.post(TOTP + "/confirm", {"code": _code(env, pending)}).status_code == 422
    assert secret != pending


# -- recovery codes -----------------------------------------------------------------------------
def test_recovery_codes_need_a_real_second_factor(env: Env) -> None:
    env.login()
    r = env.post(CODES)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "second_factor_required"
    assert env.second_factor.recovery_hashes(env.user_dn) == []


def test_recovery_codes_are_stored_hashed_and_replaced(env: Env) -> None:
    env.login()
    _enable(env)
    first = env.post(CODES).json()["codes"]
    assert len(first) == 10
    assert len(set(first)) == 10
    stored = env.second_factor.recovery_hashes(env.user_dn)
    assert stored == [hash_recovery_code(c) for c in first]
    assert not any(c in stored or c.replace("-", "") in stored for c in first)

    second = env.post(CODES).json()["codes"]
    assert set(first).isdisjoint(second)
    assert env.second_factor.recovery_hashes(env.user_dn) == [hash_recovery_code(c) for c in second]
    assert env.client.get(TOTP).json()["recovery_codes_remaining"] == 10


def test_recovery_codes_allowed_with_only_a_security_key(env: Env) -> None:
    env.login()
    _add_key(env)
    assert env.post(CODES).status_code == 200


def test_a_generated_recovery_code_logs_in_once(env: Env) -> None:
    env.login()
    _enable(env)
    code = env.post(CODES).json()["codes"][0]
    env.client.cookies.clear()
    env.csrf_token = str(env.client.get(BASE + "/csrf").json()["token"])
    assert env.login().json()["methods"] == ["totp", "recovery"]
    ok = env.post(BASE + "/second-factor", {"method": "recovery", "code": code.lower()})
    assert ok.status_code == 200
    assert env.client.get(TOTP).json()["recovery_codes_remaining"] == 9

    env.client.cookies.clear()
    env.csrf_token = str(env.client.get(BASE + "/csrf").json()["token"])
    env.login()
    assert (
        env.post(BASE + "/second-factor", {"method": "recovery", "code": code}).status_code == 401
    )


def test_users_only_touch_their_own_factors(env: Env) -> None:
    env.login()
    _enable(env)
    env.post(CODES)
    env.client.cookies.clear()
    env.csrf_token = str(env.client.get(BASE + "/csrf").json()["token"])
    assert env.login("other", "otherpass").json() == {"status": "ok", "methods": []}
    assert env.client.get(TOTP).json() == {
        "enabled": False,
        "recovery_codes_remaining": 0,
        "security_keys": 0,
    }
    assert _delete(env, confirm=True) == 404
    assert env.post(CODES).status_code == 409


def test_reauth_accepts_a_code_of_an_existing_second_factor(env: Env) -> None:
    env.login()
    secret = _enable(env)
    env.clock.advance(301)
    assert env.post(TOTP + "/begin").status_code == 403
    wrong = env.post(BASE + "/reauth", {"method": "totp", "code": "000000"})
    assert wrong.status_code == 422
    env.clock.advance(TOTP_STEP_SECONDS * 2)  # the enrolment code is used up
    ok = env.post(BASE + "/reauth", {"method": "totp", "code": _code(env, secret)})
    assert ok.status_code == 200
    assert env.post(TOTP + "/begin").status_code == 200
    assert env.post(BASE + "/reauth", {}).status_code == 422


def test_removing_the_last_factor_is_audited_and_mailed(env: Env) -> None:
    env.login()
    _enable(env)
    assert _delete(env, confirm=True) == 204
    [mail] = env.mailer.outbox
    assert mail.to == "jdoe@example.com" and "turned off" in mail.subject.lower()
    # a factor that is not the last one does not mail anybody
    _enable(env)
    _add_key(env)
    assert _delete(env) == 204
    assert len(env.mailer.outbox) == 1
