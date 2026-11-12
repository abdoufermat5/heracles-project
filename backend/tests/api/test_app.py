from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from heracles.api.app import create_app
from heracles.api.deps import CurrentUserDep
from heracles.api.errors import ApiError
from heracles.api.settings import ApiSettings, LoginSettings
from tests.api.conftest import Env
from tests.auth.fakes import FakeDirectory


def test_health_endpoints(env: Env) -> None:
    assert env.client.get("/healthz").json() == {"status": "ok"}
    ready = env.client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["directories"]["main"]["ok"] is True


def test_security_headers_and_request_id(env: Env) -> None:
    r = env.client.get("/api/v2/directories", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    bad = env.client.get("/healthz", headers={"X-Request-ID": "bad id\n<x>"})
    assert bad.headers["x-request-id"] != "bad id\n<x>"
    assert len(bad.headers["x-request-id"]) == 32


def test_extra_router_uses_current_user_and_csrf() -> None:
    directory = FakeDirectory()
    directory.add_user("jdoe", "s3cretpass")
    router = APIRouter()

    @router.get("/whoami")
    def whoami(user: CurrentUserDep) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"dn": user.dn, "directory": user.directory_id}

    @router.post("/boom")
    def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise ApiError(409, "conflict", "nope")

    app = create_app(ApiSettings(), {"main": directory}, extra_routers=[router])
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    assert client.get("/api/v2/whoami").status_code == 401
    token = client.get("/api/v2/auth/csrf").json()["token"]
    h = {"X-CSRF-Token": token}
    client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": "jdoe", "password": "s3cretpass"},
        headers=h,
    )
    who = client.get("/api/v2/whoami")
    assert who.json() == {"dn": "uid=jdoe,ou=people,dc=example,dc=com", "directory": "main"}
    assert client.post("/api/v2/boom").status_code == 403
    r = client.post("/api/v2/boom", headers=h)
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "conflict", "message": "nope"}}


def test_unhandled_exception_is_internal_error() -> None:
    router = APIRouter()

    @router.get("/crash")
    def crash() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("secret detail")

    app = create_app(ApiSettings(), {"main": FakeDirectory()}, extra_routers=[router])
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    r = client.get("/api/v2/crash")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal", "message": "Internal server error"}}


def test_header_login_requires_trusted_proxy() -> None:
    directory = FakeDirectory()
    dn = directory.add_user("jdoe", "pw")
    settings = ApiSettings(login=LoginSettings(header_enabled=True, trusted_proxies=["10.0.0.0/8"]))

    def attempt(host: str) -> int:
        app = create_app(settings, {"main": directory})
        client = TestClient(
            app, base_url="https://testserver", client=(host, 50000), raise_server_exceptions=False
        )
        token = client.get("/api/v2/auth/csrf").json()["token"]
        r = client.post(
            "/api/v2/auth/login/header",
            json={"directory": "main"},
            headers={"X-CSRF-Token": token, "AUTH_USER": "jdoe"},
        )
        if r.status_code == 200:
            assert client.get("/api/v2/auth/me").json()["dn"] == dn
        return r.status_code

    assert attempt("10.1.2.3") == 200
    assert attempt("192.0.2.9") == 401


def test_header_login_disabled_by_default(env: Env) -> None:
    r = env.post("/api/v2/auth/login/header", {"directory": "main"})
    assert r.status_code == 404


def test_oidc_routes_are_stubbed(env: Env) -> None:
    for path in ("/api/v2/auth/oidc/login", "/api/v2/auth/oidc/callback"):
        r = env.client.get(path)
        assert r.status_code == 501
        assert r.json()["error"]["code"] == "not_implemented"


def test_static_spa_with_history_fallback(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("x")
    app = create_app(
        ApiSettings(static_dir=tmp_path / "assets" / ".." / "."), {"main": FakeDirectory()}
    )
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/").text == "<html>spa</html>"
    assert client.get("/users/some/deep/link").text == "<html>spa</html>"
    js = client.get("/assets/app.js")
    assert js.text == "console.log(1)"
    assert "immutable" in js.headers["cache-control"]
    assert client.get("/%2e%2e/%2e%2e/etc/passwd").text == "<html>spa</html>"
    api_404 = client.get("/api/v2/unknown")
    assert api_404.status_code == 404
    assert api_404.json()["error"]["code"] == "not_found"
    assert client.get("/healthz").json() == {"status": "ok"}


def test_no_static_dir_means_plain_404() -> None:
    app = create_app(ApiSettings(static_dir=Path("/nonexistent")), {"main": FakeDirectory()})
    assert TestClient(app).get("/").status_code == 404
