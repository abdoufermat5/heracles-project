"""OpenID Connect sign-in against a fake provider (discovery, keys, token endpoint)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.auth.oidc import OidcSettings
from heracles.auth.passwords import lock
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app

BASE = demo.BASE
ISSUER = "https://idp.example.test/realm"
CONSOLE = "https://console.example.test"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
FAILURE = "/login?sso_error=1"


@dataclass
class FakeProvider:
    """An identity provider: whatever ``claims`` says goes into the next ID token."""

    key: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    claims: dict[str, Any] = field(default_factory=lambda: {})
    #: Changes the header / signing of the next token: (claims, key) -> token.
    sign: Callable[[dict[str, Any], rsa.RSAPrivateKey], str] | None = None
    challenges: dict[str, str] = field(default_factory=lambda: {})
    nonces: dict[str, str] = field(default_factory=lambda: {})
    token_requests: list[dict[str, list[str]]] = field(default_factory=lambda: [])
    end_session: bool = True
    down: bool = False

    def jwks(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("down")
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            doc: dict[str, Any] = {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/certs",
                "code_challenge_methods_supported": ["S256"],
            }
            if self.end_session:
                doc["end_session_endpoint"] = f"{ISSUER}/logout"
            return httpx2.Response(200, json=doc)
        if path.endswith("/certs"):
            return httpx2.Response(200, json=self.jwks())
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            code = form["code"][0]
            verifier = form["code_verifier"][0]
            digest = hashlib.sha256(verifier.encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if self.challenges.get(code) != challenge:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": ISSUER,
                "aud": "heracles",
                "sub": "subject-1",
                "iat": now,
                "exp": now + 300,
                "nonce": self.nonces[code],
                "preferred_username": "asmith",
                **self.claims,
            }
            claims = {k: v for k, v in claims.items() if v is not None}
            token = (
                self.sign(claims, self.key)
                if self.sign
                else jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})
            )
            return httpx2.Response(200, json={"id_token": token, "access_token": "a"})
        return httpx2.Response(404)

    def authorize(self, location: str, code: str = "code-1") -> str:
        """Play the provider's sign-in page: remember the request, give back a code."""
        query = parse_qs(urlparse(location).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [f"{CONSOLE}/api/v2/auth/oidc/callback"]
        self.challenges[code] = query["code_challenge"][0]
        self.nonces[code] = query["nonce"][0]
        return query["state"][0]


def make_app(directory: MemoryDirectory | None = None, **oidc: Any) -> tuple[FastAPI, FakeProvider]:
    settings = ApiSettings(
        directory_labels={"main": "Demo"},
        oidc=OidcSettings.model_validate(
            {
                "enabled": True,
                "issuer": ISSUER,
                "client_id": "heracles",
                "client_secret": "s3cret",
                "public_url": CONSOLE,
                "label": "Example SSO",
                **oidc,
            }
        ),
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": directory or demo.build_demo_directory()})
    provider = FakeProvider()
    app.state.oidc_transport = httpx2.MockTransport(provider.handler)
    return app, provider


def sign_in(client: TestClient, provider: FakeProvider, next_path: str = "/dashboard") -> Any:
    start = client.get("/api/v2/auth/oidc/login", params={"next": next_path})
    assert start.status_code == 302, start.text
    state = provider.authorize(start.headers["location"])
    return client.get("/api/v2/auth/oidc/callback", params={"code": "code-1", "state": state})


def signed_in_as(client: TestClient) -> str | None:
    me = client.get("/api/v2/auth/me")
    return str(me.json()["dn"]) if me.status_code == 200 else None


# -- off by default -------------------------------------------------------------------------------
def test_off_by_default() -> None:
    settings = ApiSettings(directory_labels={"main": "Demo"})
    with TestClient(create_full_app(settings, {"main": demo.build_demo_directory()})) as client:
        methods = client.get("/api/v2/auth/methods").json()
        assert methods == {"login_method": "form", "methods": [{"id": "form", "url": None}]}
        for path in ("login", "callback"):
            assert (
                client.get(f"/api/v2/auth/oidc/{path}", follow_redirects=False).status_code == 404
            )
        # signing out still works for a session opened before the sign-in was switched off
        out = client.get("/api/v2/auth/oidc/logout", follow_redirects=False)
        assert out.status_code == 302 and out.headers["location"] == "/login"


def test_without_a_label_the_button_text_is_left_to_the_console() -> None:
    app, _provider = make_app(label="")
    with TestClient(app) as client:
        methods = client.get("/api/v2/auth/methods").json()["methods"]
    assert {"id": "oidc", "url": "/api/v2/auth/oidc/login"} in methods


def test_enabling_needs_an_issuer_and_a_client() -> None:
    with pytest.raises(ValueError, match="issuer"):
        OidcSettings(enabled=True, client_id="x", client_secret="y")
    with pytest.raises(ValueError, match="secret"):
        OidcSettings(enabled=True, issuer=ISSUER, client_id="x")
    assert OidcSettings(enabled=True, issuer=ISSUER, client_id="x", client_auth="none").enabled


# -- the flow -------------------------------------------------------------------------------------
def test_sign_in_maps_the_claim_to_the_account_and_audits_it() -> None:
    app, provider = make_app()
    with TestClient(app, follow_redirects=False) as client:
        methods = client.get("/api/v2/auth/methods").json()["methods"]
        assert {"id": "oidc", "url": "/api/v2/auth/oidc/login", "label": "Example SSO"} in methods
        done = sign_in(client, provider)
        assert done.status_code == 302 and done.headers["location"] == "/dashboard"
        assert signed_in_as(client) == ASMITH
        # client authentication and PKCE reached the token endpoint
        sent = provider.token_requests[-1]
        assert sent["grant_type"] == ["authorization_code"] and "code_verifier" in sent
        assert "client_secret" not in sent  # client_secret_basic by default
    directory = app.state.heracles.directories["main"]
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=login)"))
    assert any("method: oidc" in " ".join(e.texts("hrcAuditAttributes")) for e in events)


def test_logout_ends_both_sessions() -> None:
    app, provider = make_app()
    with TestClient(app, follow_redirects=False) as client:
        sign_in(client, provider)
        out = client.get("/api/v2/auth/oidc/logout")
        target = urlparse(out.headers["location"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == f"{ISSUER}/logout"
        query = parse_qs(target.query)
        assert query["post_logout_redirect_uri"] == [f"{CONSOLE}/login"]
        assert query["id_token_hint"][0].count(".") == 2
        assert signed_in_as(client) is None
    provider.end_session = False
    app2, provider2 = make_app()
    provider2.end_session = False
    with TestClient(app2, follow_redirects=False) as client:
        sign_in(client, provider2)
        assert client.get("/api/v2/auth/oidc/logout").headers["location"] == "/login"


# -- ID token checks ------------------------------------------------------------------------------
def _hs256_with_public_key(claims: dict[str, Any], key: rsa.RSAPrivateKey) -> str:
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    import hmac

    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    body = b64(json.dumps(claims).encode())
    sig = hmac.new(public, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def _unsigned(claims: dict[str, Any], _key: rsa.RSAPrivateKey) -> str:
    return jwt.encode(claims, None, algorithm="none")  # pyright: ignore[reportArgumentType]


def _other_key(claims: dict[str, Any], _key: rsa.RSAPrivateKey) -> str:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return jwt.encode(claims, other, algorithm="RS256", headers={"kid": "k1"})


@pytest.mark.parametrize(
    ("claims", "sign"),
    [
        ({"iss": "https://evil.example.test"}, None),
        ({"aud": "another-client"}, None),
        ({"aud": ["heracles", "another"], "azp": "another"}, None),
        ({"nonce": "not-the-one"}, None),
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, None),
        ({"sub": None}, None),
        ({}, _unsigned),
        ({}, _hs256_with_public_key),
        ({}, _other_key),
    ],
    ids=["iss", "aud", "azp", "nonce", "expired", "no-sub", "none", "hs256-public-key", "bad-sig"],
)
def test_bad_id_tokens_are_refused(
    claims: dict[str, Any], sign: Callable[[dict[str, Any], rsa.RSAPrivateKey], str] | None
) -> None:
    app, provider = make_app()
    provider.claims = claims
    provider.sign = sign
    with TestClient(app, follow_redirects=False) as client:
        done = sign_in(client, provider)
        assert done.headers["location"] == FAILURE
        assert signed_in_as(client) is None


# -- state ----------------------------------------------------------------------------------------
def test_state_must_come_from_this_browser_and_is_single_use() -> None:
    app, provider = make_app()
    with TestClient(app, follow_redirects=False) as client:
        start = client.get("/api/v2/auth/oidc/login")
        state = provider.authorize(start.headers["location"])
        # another browser (no state cookie) cannot complete it
        with TestClient(app, follow_redirects=False) as other:
            hijack = other.get(
                "/api/v2/auth/oidc/callback", params={"code": "code-1", "state": state}
            )
            assert hijack.headers["location"] == FAILURE and signed_in_as(other) is None
        ok = client.get("/api/v2/auth/oidc/callback", params={"code": "code-1", "state": state})
        assert ok.headers["location"] == "/"
        client.cookies.set("heracles_oidc", state, path="/api/v2/auth/oidc")
        again = client.get("/api/v2/auth/oidc/callback", params={"code": "code-1", "state": state})
        assert again.headers["location"] == FAILURE
        # an error from the provider
        err = client.get("/api/v2/auth/oidc/callback", params={"error": "access_denied"})
        assert err.headers["location"] == FAILURE
        # hostile values fall back to the form, never a server error
        client.cookies.set("heracles_oidc", "abc", path="/api/v2/auth/oidc")
        odd = client.get("/api/v2/auth/oidc/callback", params={"code": "c", "state": "é"})
        assert odd.status_code == 302 and odd.headers["location"] == FAILURE


# -- the account ----------------------------------------------------------------------------------
def test_no_account_two_accounts_and_locked_accounts_are_refused() -> None:
    directory = demo.build_demo_directory()
    app, provider = make_app(directory, attribute="sn")
    entry = directory.get(ASMITH)
    assert entry is not None
    surname = entry.text("sn") or ""
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"preferred_username": "nobody-has-this-surname"}
        assert sign_in(client, provider).headers["location"] == FAILURE
        twin = f"uid=asmith2,ou=people,{BASE}"
        directory.add(
            twin,
            {
                "objectClass": [b"inetOrgPerson"],
                "uid": [b"asmith2"],
                "cn": [b"Twin"],
                "sn": [surname.encode()],
            },
        )
        provider.claims = {"preferred_username": surname}
        assert sign_in(client, provider).headers["location"] == FAILURE
        directory.delete(twin)
        assert sign_in(client, provider).headers["location"] == "/dashboard"

    stored = entry.text("userPassword") or "{SSHA}x"
    directory.modify(ASMITH, [Modification("replace", "userPassword", [lock(stored).encode()])])
    app2, provider2 = make_app(directory)
    with TestClient(app2, follow_redirects=False) as client:
        assert sign_in(client, provider2).headers["location"] == FAILURE
        assert signed_in_as(client) is None


def test_email_needs_verification_and_groups_can_be_required() -> None:
    entry = demo.build_demo_directory().get(ASMITH)
    assert entry is not None
    mail = entry.text("mail") or ""
    app, provider = make_app(claim="email", attribute="mail")
    with TestClient(app, follow_redirects=False) as client:
        provider.claims = {"email": mail}
        assert sign_in(client, provider).headers["location"] == FAILURE
        provider.claims = {"email": mail, "email_verified": True}
        assert sign_in(client, provider).headers["location"] == "/dashboard"

    app2, provider2 = make_app(allowed_groups=["console-admins"])
    with TestClient(app2, follow_redirects=False) as client:
        provider2.claims = {"groups": ["staff"]}
        assert sign_in(client, provider2).headers["location"] == FAILURE
        provider2.claims = {"groups": ["staff", "console-admins"]}
        assert sign_in(client, provider2).headers["location"] == "/dashboard"


# -- fallback -------------------------------------------------------------------------------------
def test_the_password_form_works_while_the_provider_is_down() -> None:
    app, provider = make_app()
    provider.down = True
    calls: list[str] = []
    down = provider.handler

    def counted(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        return down(request)

    app.state.oidc_transport = httpx2.MockTransport(counted)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/api/v2/auth/methods").status_code == 200
        assert calls == []  # listing the methods never calls the provider
        start = client.get("/api/v2/auth/oidc/login")
        assert start.headers["location"] == FAILURE
        # a second click right after does not wait for the provider again
        assert client.get("/api/v2/auth/oidc/login").headers["location"] == FAILURE
        assert len(calls) == 1
        token = client.get("/api/v2/auth/csrf").json()["token"]
        r = client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "admin", "password": demo.DEMO_PASSWORD},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200, r.text
    directory = app.state.heracles.directories["main"]
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=login)"))
    assert any("method: password" in " ".join(e.texts("hrcAuditAttributes")) for e in events)
