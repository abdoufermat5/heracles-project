"""WebAuthn second factor and enrolment through API v2 (py_webauthn verification is mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from heracles.auth.second_factor import WebAuthnCredential
from tests.api.conftest import Env

CRED_ID = b"credential-id-1"
CRED_B64 = bytes_to_base64url(CRED_ID)
ASSERTION: dict[str, Any] = {
    "id": CRED_B64,
    "rawId": CRED_B64,
    "type": "public-key",
    "response": {},
}
SF = "/api/v2/auth/second-factor"


def _add_key(env: Env, sign_count: int = 5, cred_id: bytes = CRED_ID) -> None:
    env.second_factor.add_webauthn_credential(
        env.user_dn, WebAuthnCredential(cred_id, b"pub", sign_count, "key")
    )


def _verify_ok(new_count: int = 6) -> Any:
    return patch(
        "heracles.auth.webauthn.verify_authentication_response",
        return_value=SimpleNamespace(new_sign_count=new_count),
    )


def _begin(env: Env) -> dict[str, Any]:
    r = env.post("/api/v2/auth/webauthn/options")
    assert r.status_code == 200
    return r.json()["options"]


# -- login --------------------------------------------------------------------------------------
def test_login_offers_webauthn(env: Env) -> None:
    _add_key(env)
    assert env.login().json() == {"status": "second_factor", "methods": ["webauthn"]}


def test_options_and_success(env: Env) -> None:
    _add_key(env)
    env.login()
    options = _begin(env)
    assert options["allowCredentials"][0]["id"] == CRED_B64
    with _verify_ok(9) as verify:
        r = env.post(SF, {"method": "webauthn", "credential": ASSERTION})
    assert r.status_code == 200
    assert verify.call_args.kwargs["credential_current_sign_count"] == 5
    assert env.second_factor.webauthn_credentials(env.user_dn)[0].sign_count == 9
    assert env.client.get("/api/v2/auth/me").status_code == 200


def test_options_require_pending_webauthn_session(env: Env) -> None:
    assert env.post("/api/v2/auth/webauthn/options").status_code == 401
    env.second_factor.set_totp_secret(env.user_dn, "JBSWY3DPEHPK3PXP")
    env.login()
    assert env.post("/api/v2/auth/webauthn/options").status_code == 422


def test_assertion_without_options_is_refused(env: Env) -> None:
    _add_key(env)
    env.login()
    with _verify_ok():
        r = env.post(SF, {"method": "webauthn", "credential": ASSERTION})
    assert r.status_code == 401


def test_challenge_is_single_use(env: Env) -> None:
    _add_key(env)
    env.login()
    _begin(env)
    with patch(
        "heracles.auth.webauthn.verify_authentication_response",
        side_effect=InvalidAuthenticationResponse("bad signature"),
    ):
        assert env.post(SF, {"method": "webauthn", "credential": ASSERTION}).status_code == 401
    with _verify_ok():  # even a valid assertion cannot reuse the consumed challenge
        assert env.post(SF, {"method": "webauthn", "credential": ASSERTION}).status_code == 401
    assert env.client.get("/api/v2/auth/me").status_code == 401


def test_expired_challenge(env: Env) -> None:
    _add_key(env)
    env.login()
    _begin(env)
    env.clock.advance(121)
    with _verify_ok():
        r = env.post(SF, {"method": "webauthn", "credential": ASSERTION})
    assert r.status_code == 401


def test_counter_regression_is_rejected(env: Env) -> None:
    _add_key(env, sign_count=10)
    env.login()
    _begin(env)
    with patch(
        "heracles.auth.webauthn.verify_authentication_response",
        side_effect=InvalidAuthenticationResponse("sign count not greater"),
    ):
        r = env.post(SF, {"method": "webauthn", "credential": ASSERTION})
    assert r.status_code == 401
    assert env.second_factor.webauthn_credentials(env.user_dn)[0].sign_count == 10


def test_unknown_credential_and_malformed_body(env: Env) -> None:
    _add_key(env)
    env.login()
    _begin(env)
    other = bytes_to_base64url(b"someone-else")
    with _verify_ok():
        r = env.post(SF, {"method": "webauthn", "credential": {"rawId": other, "id": other}})
    assert r.status_code == 401
    _begin(env)
    assert env.post(SF, {"method": "webauthn", "credential": {"foo": 1}}).status_code == 401
    _begin(env)
    assert env.post(SF, {"method": "webauthn"}).status_code == 401


def test_failures_count_towards_lockout(env: Env) -> None:
    _add_key(env)
    env.login()
    for _ in range(5):
        assert env.post(SF, {"method": "webauthn", "credential": ASSERTION}).status_code == 401
    r = env.post(SF, {"method": "webauthn", "credential": ASSERTION})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"
    assert env.post("/api/v2/auth/webauthn/options").status_code == 401


# -- enrolment ----------------------------------------------------------------------------------
def test_enrolment_requires_login(env: Env) -> None:
    base = "/api/v2/auth/webauthn/credentials"
    assert env.client.get(base).status_code == 401
    assert env.post(base + "/options").status_code == 401
    assert env.post(base, {"label": "x", "credential": {}}).status_code == 401
    assert env.client.delete(f"{base}/abc", headers=env.headers()).status_code == 401


def test_enrolment_pending_second_factor_is_refused(env: Env) -> None:
    _add_key(env)
    env.login()
    assert env.post("/api/v2/auth/webauthn/credentials/options").status_code == 401


def test_register_list_delete(env: Env) -> None:
    base = "/api/v2/auth/webauthn/credentials"
    env.login()
    assert env.client.get(base).json() == []
    new_id = b"new-key"
    opts = env.post(base + "/options")
    assert opts.status_code == 200
    assert opts.json()["options"]["user"]["name"] == "jdoe"
    with patch(
        "heracles.auth.webauthn.verify_registration_response",
        return_value=SimpleNamespace(
            credential_id=new_id, credential_public_key=b"pk", sign_count=0
        ),
    ):
        r = env.post(base, {"label": " Yubi ", "credential": {"id": "x"}})
    assert r.status_code == 201
    assert r.json() == {"id": bytes_to_base64url(new_id), "label": "Yubi", "sign_count": 0}
    assert [c["label"] for c in env.client.get(base).json()] == ["Yubi"]

    # exclusion list in later registration options
    again = env.post(base + "/options").json()["options"]
    assert again["excludeCredentials"][0]["id"] == bytes_to_base64url(new_id)

    d = env.client.delete(f"{base}/{bytes_to_base64url(new_id)}", headers=env.headers())
    assert d.status_code == 204
    assert env.client.get(base).json() == []
    d = env.client.delete(f"{base}/{bytes_to_base64url(new_id)}", headers=env.headers())
    assert d.status_code == 404


def test_register_needs_fresh_challenge_and_valid_response(env: Env) -> None:
    base = "/api/v2/auth/webauthn/credentials"
    env.login()
    ok = SimpleNamespace(credential_id=b"k", credential_public_key=b"pk", sign_count=0)
    with patch("heracles.auth.webauthn.verify_registration_response", return_value=ok):
        assert env.post(base, {"label": "a", "credential": {}}).status_code == 422  # no options
        env.post(base + "/options")
        env.clock.advance(121)
        assert env.post(base, {"label": "a", "credential": {}}).status_code == 422  # expired
    env.post(base + "/options")
    with patch(
        "heracles.auth.webauthn.verify_registration_response", side_effect=ValueError("nope")
    ):
        assert env.post(base, {"label": "a", "credential": {}}).status_code == 422
    assert env.client.get(base).json() == []


def test_register_rejects_duplicate_credential(env: Env) -> None:
    base = "/api/v2/auth/webauthn/credentials"
    _add_key(env, cred_id=b"dup")
    # complete login via the key to get a full session
    env.login()
    _begin(env)
    dup = bytes_to_base64url(b"dup")
    with _verify_ok():
        env.post(SF, {"method": "webauthn", "credential": {"rawId": dup, "id": dup}})
    env.post(base + "/options")
    ok = SimpleNamespace(credential_id=b"dup", credential_public_key=b"pk", sign_count=0)
    with patch("heracles.auth.webauthn.verify_registration_response", return_value=ok):
        assert env.post(base, {"label": "a", "credential": {}}).status_code == 422


def test_users_cannot_touch_other_users_credentials(env: Env) -> None:
    base = "/api/v2/auth/webauthn/credentials"
    other_dn = env.user_dn.replace("uid=jdoe", "uid=other")
    env.second_factor.add_webauthn_credential(
        other_dn, WebAuthnCredential(b"theirs", b"pk", 0, "theirs")
    )
    env.login()
    assert env.client.get(base).json() == []
    d = env.client.delete(f"{base}/{bytes_to_base64url(b'theirs')}", headers=env.headers())
    assert d.status_code == 404
    assert len(env.second_factor.webauthn_credentials(other_dn)) == 1
