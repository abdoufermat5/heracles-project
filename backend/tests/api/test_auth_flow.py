from __future__ import annotations

import pyotp

from heracles.auth.second_factor import hash_recovery_code
from tests.api.conftest import Env


def test_directories(env: Env) -> None:
    r = env.client.get("/api/v2/directories")
    assert r.status_code == 200
    assert r.json() == [{"id": "main", "label": "Main directory"}]


def test_csrf_endpoint_sets_cookie_and_is_stable(env: Env) -> None:
    r = env.client.get("/api/v2/auth/csrf")
    assert r.json()["token"] == env.csrf_token
    assert env.client.cookies.get("heracles_csrf") == env.csrf_token


def test_full_login_me_logout(env: Env) -> None:
    r = env.login()
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "methods": []}
    set_cookie = r.headers["set-cookie"].lower()
    assert "heracles_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie

    me = env.client.get("/api/v2/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "dn": env.user_dn,
        "uid": "jdoe",
        "display_name": "John Doe",
        "avatar_url": None,
        "is_admin": True,
        "directory": "main",
        "base": "dc=example,dc=com",
    }

    out = env.post("/api/v2/auth/logout")
    assert out.status_code == 204
    assert env.logout_calls == [env.user_dn]
    assert env.client.get("/api/v2/auth/me").status_code == 401


def test_me_requires_login_with_api_error_format(env: Env) -> None:
    r = env.client.get("/api/v2/auth/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthenticated", "message": "Authentication required"}}


def test_wrong_password_and_unknown_user_are_indistinguishable(env: Env) -> None:
    a = env.login(password="nope")
    b = env.login(username="ghost", password="nope")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()
    assert a.json()["error"]["code"] == "unauthenticated"


def test_empty_password_never_binds(env: Env) -> None:
    r = env.login(password="")
    assert r.status_code == 401
    assert env.directory.bind_attempts == []


def test_filter_injection_is_escaped(env: Env) -> None:
    r = env.login(username="*", password="x")
    assert r.status_code == 401
    r = env.login(username="jdoe)(uid=*", password="s3cretpass")
    assert r.status_code == 401
    assert env.directory.bind_attempts == []


def test_validation_error_format(env: Env) -> None:
    r = env.post("/api/v2/auth/login", {"directory": "main"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation"
    assert set(err["fields"]) == {"username", "password"}


def test_unknown_directory(env: Env) -> None:
    r = env.post("/api/v2/auth/login", {"directory": "zzz", "username": "a", "password": "b"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"directory": "Unknown directory"}


def test_not_found_format(env: Env) -> None:
    r = env.client.get("/api/v2/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_session_rotation_on_login(env: Env) -> None:
    env.login()
    first = env.client.cookies.get("heracles_session")
    assert first
    env.login()
    second = env.client.cookies.get("heracles_session")
    assert second and second != first
    assert env.sessions.get(first) is None


def test_session_idle_and_absolute_expiry(env: Env) -> None:
    env.login()
    env.clock.advance(29 * 60)
    assert env.client.get("/api/v2/auth/me").status_code == 200  # refreshes last_seen
    env.clock.advance(29 * 60)
    assert env.client.get("/api/v2/auth/me").status_code == 200
    env.clock.advance(31 * 60)
    assert env.client.get("/api/v2/auth/me").status_code == 401

    env.login()
    for _ in range(25):  # stay active but exceed 12 hours in total
        env.clock.advance(29 * 60)
        env.client.get("/api/v2/auth/me")
    assert env.client.get("/api/v2/auth/me").status_code == 401


def test_logout_without_session_is_ok(env: Env) -> None:
    assert env.post("/api/v2/auth/logout").status_code == 204


# -- second factor ---------------------------------------------------------------------------------
def _enroll(env: Env) -> str:
    secret = pyotp.random_base32()
    env.second_factor.set_totp_secret(env.user_dn, secret)
    return secret


def test_totp_flow(env: Env) -> None:
    secret = _enroll(env)
    env.second_factor.set_recovery_hashes(env.user_dn, [hash_recovery_code("ABCDE-FGHJK")])
    r = env.login()
    assert r.json() == {"status": "second_factor", "methods": ["totp", "recovery"]}
    # Not yet authenticated.
    assert env.client.get("/api/v2/auth/me").status_code == 401

    bad = env.post("/api/v2/auth/second-factor", {"method": "totp", "code": "000000"})
    assert bad.status_code == 401
    assert env.client.get("/api/v2/auth/me").status_code == 401

    pending_cookie = env.client.cookies.get("heracles_session")
    code = pyotp.TOTP(secret).at(int(env.clock.now))
    ok = env.post("/api/v2/auth/second-factor", {"method": "totp", "code": code})
    assert ok.status_code == 200
    assert ok.json() == {"status": "ok"}
    assert env.client.cookies.get("heracles_session") != pending_cookie
    assert env.client.get("/api/v2/auth/me").status_code == 200


def test_totp_accepts_adjacent_step_but_not_replay(env: Env) -> None:
    secret = _enroll(env)
    env.login()
    previous = pyotp.TOTP(secret).at(int(env.clock.now) - 30)
    assert (
        env.post("/api/v2/auth/second-factor", {"method": "totp", "code": previous}).status_code
        == 200
    )
    env.login()
    # same step again (replay) is refused
    assert (
        env.post("/api/v2/auth/second-factor", {"method": "totp", "code": previous}).status_code
        == 401
    )
    far = pyotp.TOTP(secret).at(int(env.clock.now) + 120)
    assert (
        env.post("/api/v2/auth/second-factor", {"method": "totp", "code": far}).status_code == 401
    )


def test_recovery_code_is_single_use(env: Env) -> None:
    _enroll(env)
    env.second_factor.set_recovery_hashes(env.user_dn, [hash_recovery_code("ABCDE-FGHJK")])
    env.login()
    r = env.post("/api/v2/auth/second-factor", {"method": "recovery", "code": "abcde-fghjk"})
    assert r.status_code == 200
    env.login()
    # the only code was consumed: the method is no longer offered at login
    assert env.login().json()["methods"] == ["totp"]
    r = env.post("/api/v2/auth/second-factor", {"method": "recovery", "code": "ABCDE-FGHJK"})
    assert r.status_code == 422


def test_second_factor_requires_pending_session(env: Env) -> None:
    r = env.post("/api/v2/auth/second-factor", {"method": "totp", "code": "123456"})
    assert r.status_code == 401


def test_second_factor_failures_drop_session(env: Env) -> None:
    _enroll(env)
    env.login()
    for _ in range(5):
        assert (
            env.post("/api/v2/auth/second-factor", {"method": "totp", "code": "000000"}).status_code
            == 401
        )
    r = env.post("/api/v2/auth/second-factor", {"method": "totp", "code": "000000"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_second_factor_guesses_are_throttled_across_logins(env: Env) -> None:
    secret = _enroll(env)
    # A right password renews the per-session budget and the login throttle every time:
    # exhausted sessions must back the account off (3 free ones in the test limiter).
    for _ in range(3):
        assert env.login().status_code == 200
        for _ in range(5):
            bad = env.post("/api/v2/auth/second-factor", {"method": "totp", "code": "000000"})
            assert bad.status_code == 401
    assert env.login().status_code == 200
    # even the right code is refused while the account is throttled ...
    code = pyotp.TOTP(secret).at(int(env.clock.now))
    blocked = env.post("/api/v2/auth/second-factor", {"method": "totp", "code": code})
    assert blocked.status_code == 429
    # ... and works once the delay is over
    env.clock.advance(120)
    env.login()
    code = pyotp.TOTP(secret).at(int(env.clock.now))
    assert (
        env.post("/api/v2/auth/second-factor", {"method": "totp", "code": code}).status_code == 200
    )


def test_unavailable_method_is_rejected(env: Env) -> None:
    _enroll(env)
    env.login()
    r = env.post("/api/v2/auth/second-factor", {"method": "recovery", "code": "x"})
    assert r.status_code == 422
