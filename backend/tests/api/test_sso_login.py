"""CAS and HTTP Basic login routes, and the public login-method discovery."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.auth.sso import SsoSettings
from heracles.server import create_full_app

BASE = demo.BASE
SUCCESS = """<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
<cas:authenticationSuccess><cas:user>{user}</cas:user></cas:authenticationSuccess>
</cas:serviceResponse>"""
FAILURE = """<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
<cas:authenticationFailure code="INVALID_TICKET">no</cas:authenticationFailure>
</cas:serviceResponse>"""


def make_app(sso: SsoSettings) -> FastAPI:
    settings = ApiSettings(directory_labels={"main": "Demo"}, sso=sso)
    settings.session.cookie_secure = False
    return create_full_app(settings, {"main": demo.build_demo_directory()})


def fake_cas(app: FastAPI, users: dict[str, str]) -> list[httpx2.Request]:
    """Install a fake CAS server: ``ticket -> user``; unknown tickets fail."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        user = users.get(request.url.params.get("ticket", ""))
        return httpx2.Response(200, text=SUCCESS.format(user=user) if user else FAILURE)

    app.state.cas_transport = httpx2.MockTransport(handler)
    return seen


CAS = SsoSettings(
    login_method="cas",
    cas_enabled=True,
    cas_host="cas.example.org",
    cas_service_name="https://h.test",
)


@pytest.fixture
def cas_app() -> FastAPI:
    return make_app(CAS)


@pytest.fixture
def cas_client(cas_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(cas_app, follow_redirects=False) as client:
        yield client


def test_methods_default_is_form() -> None:
    with TestClient(make_app(SsoSettings())) as client:
        body = client.get("/api/v2/auth/methods").json()
    assert body == {"login_method": "form", "methods": [{"id": "form", "url": None}]}


def test_methods_lists_enabled_methods(cas_client: TestClient) -> None:
    body = cas_client.get("/api/v2/auth/methods").json()
    assert body["login_method"] == "cas"
    assert {"id": "cas", "url": "/api/v2/auth/cas/login"} in body["methods"]
    assert cas_client.get("/api/v2/auth/methods?directory=zzz").status_code == 422


def test_methods_ignores_unusable_primary() -> None:
    app = make_app(SsoSettings(login_method="cas"))  # no host: CAS unusable
    with TestClient(app) as client:
        assert client.get("/api/v2/auth/methods").json()["login_method"] == "form"


def test_cas_login_redirects_to_the_server(cas_client: TestClient) -> None:
    r = cas_client.get("/api/v2/auth/cas/login", params={"next": "/types/user"})
    assert r.status_code == 302
    target = urlparse(r.headers["location"])
    assert (target.scheme, target.netloc, target.path) == (
        "https",
        "cas.example.org:443",
        "/cas/login",
    )
    service = urlparse(parse_qs(target.query)["service"][0])
    assert service.netloc == "h.test" and service.path == "/api/v2/auth/cas/callback"
    assert parse_qs(service.query) == {"directory": ["main"], "next": ["/types/user"]}


def test_cas_login_refuses_open_redirects(cas_client: TestClient) -> None:
    r = cas_client.get("/api/v2/auth/cas/login", params={"next": "//evil.example"})
    service = parse_qs(urlparse(r.headers["location"]).query)["service"][0]
    assert parse_qs(urlparse(service).query)["next"] == ["/"]


def test_cas_disabled_is_404() -> None:
    with TestClient(make_app(SsoSettings()), follow_redirects=False) as client:
        assert client.get("/api/v2/auth/cas/login").status_code == 404
        assert client.get("/api/v2/auth/cas/callback?ticket=x").status_code == 404


def test_cas_without_public_name_refuses_unknown_hosts() -> None:
    """The service URL is built from the request Host only when that host is allowed."""
    sso = SsoSettings(login_method="cas", cas_enabled=True, cas_host="cas.example.org")
    app = make_app(sso)
    with TestClient(app, follow_redirects=False) as client:
        ok = client.get("/api/v2/auth/cas/login")  # "testserver" is allowed by default
        assert ok.status_code == 302
        assert (
            "service=http%3A%2F%2Ftestserver%2Fapi%2Fv2%2Fauth%2Fcas%2Fcallback"
            in (ok.headers["location"])
        )
        forged = client.get("/api/v2/auth/cas/login", headers={"Host": "evil.example"})
        assert forged.status_code == 400
        assert forged.json()["error"]["code"] == "untrusted_host"
        assert (
            client.get(
                "/api/v2/auth/cas/callback?ticket=t", headers={"Host": "evil.example"}
            ).status_code
            == 400
        )
    settings = ApiSettings(
        directory_labels={"main": "Demo"}, sso=sso, allowed_hosts=["*.corp.test"]
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": demo.build_demo_directory()})
    with TestClient(app, follow_redirects=False) as client:
        assert (
            client.get("/api/v2/auth/cas/login", headers={"Host": "h.corp.test"}).status_code == 302
        )
        assert (
            client.get("/api/v2/auth/cas/login", headers={"Host": "evil.example"}).status_code
            == 400
        )


def test_cas_callback_opens_a_session(cas_app: FastAPI, cas_client: TestClient) -> None:
    seen = fake_cas(cas_app, {"ST-1": "asmith"})
    r = cas_client.get(
        "/api/v2/auth/cas/callback",
        params={"ticket": "ST-1", "directory": "main", "next": "/types/user"},
    )
    assert r.status_code == 302 and r.headers["location"] == "/types/user"
    assert seen[0].url.params["service"].startswith("https://h.test/api/v2/auth/cas/callback")
    assert cas_client.cookies.get("heracles_sso") == "cas"
    me = cas_client.get("/api/v2/auth/me")
    assert me.status_code == 200 and me.json()["uid"] == "asmith"


def test_cas_callback_rejects_bad_tickets_and_unknown_accounts(
    cas_app: FastAPI, cas_client: TestClient
) -> None:
    fake_cas(cas_app, {"ST-2": "nobody"})
    for ticket in ("ST-bad", "ST-2", ""):
        r = cas_client.get("/api/v2/auth/cas/callback", params={"ticket": ticket})
        assert r.status_code == 302 and r.headers["location"] == "/login?sso_error=1"
    assert cas_client.get("/api/v2/auth/me").status_code == 401


def test_cas_callback_second_factor(cas_app: FastAPI, cas_client: TestClient) -> None:
    fake_cas(cas_app, {"ST-1": "asmith"})

    def methods_for(_dn: str) -> list[str]:
        return ["totp"]

    cas_app.state.heracles.second_factor.methods_for = methods_for
    r = cas_client.get("/api/v2/auth/cas/callback", params={"ticket": "ST-1", "next": "/x"})
    assert r.status_code == 302
    assert r.headers["location"] == "/login/second-factor?methods=totp&redirect=%2Fx"
    assert cas_client.get("/api/v2/auth/me").status_code == 401  # still pending


def test_cas_logout_ends_both_sessions(cas_app: FastAPI, cas_client: TestClient) -> None:
    fake_cas(cas_app, {"ST-1": "asmith"})
    cas_client.get("/api/v2/auth/cas/callback", params={"ticket": "ST-1"})
    assert cas_client.get("/api/v2/auth/me").status_code == 200
    r = cas_client.get("/api/v2/auth/cas/logout")
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://cas.example.org:443/cas/logout?service=")
    assert "heracles_sso" not in cas_client.cookies
    assert cas_client.get("/api/v2/auth/me").status_code == 401


def test_cas_logout_without_cas(cas_client: TestClient) -> None:
    with TestClient(make_app(SsoSettings()), follow_redirects=False) as client:
        r = client.get("/api/v2/auth/cas/logout")
        assert r.status_code == 302 and r.headers["location"] == "/login"


# -- HTTP Basic ---------------------------------------------------------------------------------
def basic(user: str, password: str) -> dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
def basic_client() -> Iterator[TestClient]:
    app = make_app(SsoSettings(login_method="http-basic", http_auth_enabled=True))
    with TestClient(app, follow_redirects=False) as client:
        yield client


def test_basic_challenges_without_credentials(basic_client: TestClient) -> None:
    r = basic_client.get("/api/v2/auth/login/basic")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Basic realm=")
    methods = basic_client.get("/api/v2/auth/methods").json()
    assert methods["login_method"] == "http-basic"


def test_basic_validates_by_bind(basic_client: TestClient) -> None:
    bad = basic_client.get("/api/v2/auth/login/basic", headers=basic("asmith", "wrong"))
    assert bad.status_code == 401 and "WWW-Authenticate" in bad.headers
    ok = basic_client.get(
        "/api/v2/auth/login/basic", headers=basic("asmith", "heracles"), params={"next": "/me"}
    )
    assert ok.status_code == 302 and ok.headers["location"] == "/me"
    assert basic_client.get("/api/v2/auth/me").json()["uid"] == "asmith"


def test_basic_malformed_header(basic_client: TestClient) -> None:
    for header in ("Basic !!!", "Bearer abc", "Basic " + base64.b64encode(b"nocolon").decode()):
        r = basic_client.get("/api/v2/auth/login/basic", headers={"Authorization": header})
        assert r.status_code == 401


def test_basic_disabled_is_404() -> None:
    with TestClient(make_app(SsoSettings())) as client:
        assert client.get("/api/v2/auth/login/basic", headers=basic("a", "b")).status_code == 404


def test_basic_is_rate_limited(basic_client: TestClient) -> None:
    codes: list[int] = []
    for _ in range(12):
        codes.append(
            basic_client.get("/api/v2/auth/login/basic", headers=basic("asmith", "no")).status_code
        )
    assert 429 in codes
