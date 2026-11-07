from __future__ import annotations

from tests.api.conftest import Env


def test_post_without_csrf_header_is_forbidden(env: Env) -> None:
    r = env.client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": "jdoe", "password": "s3cretpass"},
    )
    assert r.status_code == 403
    assert r.json() == {"error": {"code": "forbidden", "message": "Missing CSRF token"}}


def test_post_with_wrong_csrf_header_is_forbidden(env: Env) -> None:
    r = env.client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": "jdoe", "password": "s3cretpass"},
        headers={"X-CSRF-Token": "forged"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "Invalid CSRF token"


def test_post_without_cookie_is_forbidden(env: Env) -> None:
    env.client.cookies.clear()
    r = env.post("/api/v2/auth/logout")
    assert r.status_code == 403


def test_safe_methods_are_exempt(env: Env) -> None:
    env.client.cookies.clear()
    assert env.client.get("/api/v2/directories").status_code == 200
    assert env.client.options("/api/v2/auth/login").status_code in (200, 405)


def test_v1_is_exempt_from_csrf(env: Env) -> None:
    env.client.cookies.clear()
    r = env.client.post("/api/v1/login", json={"username": "jdoe", "password": "s3cretpass"})
    assert r.status_code == 200
    token = r.json()["token"]
    out = env.client.post("/api/v1/logout", headers={"X-Session-Token": token})
    assert out.status_code == 204
    assert env.sessions.get(token) is None


def test_v1_login_failure(env: Env) -> None:
    r = env.client.post("/api/v1/login", json={"username": "jdoe", "password": "bad"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_rate_limit_backoff_and_reset(env: Env) -> None:
    for _ in range(3):
        assert env.login(password="bad").status_code == 401
    # the third failure triggered the first delay (2 s)
    blocked = env.login(password="s3cretpass")
    assert blocked.status_code == 429
    err = blocked.json()["error"]
    assert err["code"] == "rate_limited"
    assert blocked.headers["retry-after"] == "2"
    assert env.directory.bind_attempts.count((env.user_dn, "s3cretpass")) == 0

    env.clock.advance(2.5)
    assert env.login(password="bad").status_code == 401  # second block: 4 s
    env.clock.advance(3)
    assert env.login().status_code == 429
    env.clock.advance(2)
    ok = env.login()
    assert ok.status_code == 200
    # success clears the counter
    assert env.login(password="bad").status_code == 401


def test_rate_limit_is_per_login(env: Env) -> None:
    for _ in range(5):
        env.login(password="bad")
    assert env.login(username="other", password="otherpass").status_code == 200
