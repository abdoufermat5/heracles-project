"""OpenID Connect sign-in: Heracles as a relying party (authorization code flow with PKCE).

Off by default (``api.oidc.enabled``). The settings come from the configuration file only,
never from the directory-stored configuration: whoever may edit that must not be able to
point the sign-in at another provider.

This module holds what does not depend on HTTP routing: the settings, the provider's
discovery document and keys, the pending logins and the ID token checks.
:mod:`heracles.auth.oidc_routes` drives the browser through it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, cast
from urllib.parse import quote_plus, urlencode

import httpx2
import jwt
from pydantic import BaseModel, Field, model_validator

from heracles.storage import Database

#: Signature algorithms accepted on an ID token. Asymmetric only: ``none`` and the HMAC
#: algorithms (whose key would be the provider's public key) are refused.
ALGORITHMS: Final = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
)
#: Clock skew tolerated on ``exp`` and ``iat`` (seconds).
LEEWAY: Final = 60
#: How long a pending login (between the redirect and the callback) stays usable.
PENDING_SECONDS: Final = 600.0
#: How long the discovery document and the keys are reused.
CACHE_SECONDS: Final = 600.0
#: Least time between two key downloads caused by an unknown key id.
REFETCH_SECONDS: Final = 30.0
CLIENT_AUTH: Final = ("client_secret_basic", "client_secret_post", "none")


class OidcError(Exception):
    """The sign-in cannot go on (the message is for the log, not for the browser)."""


class OidcSettings(BaseModel):
    """``api.oidc``: the identity provider and how its people map to directory entries."""

    enabled: bool = False
    #: Issuer URL; its discovery document must state the same issuer.
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    #: Read the client secret from this file (exclusive with ``client_secret``).
    client_secret_file: str = ""
    client_auth: str = "client_secret_basic"
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    #: ID token claim naming the person.
    claim: str = "preferred_username"
    #: Directory attribute the claim is matched against (empty: the login attribute).
    attribute: str = ""
    #: Text of the sign-in button ("Sign in with ...").
    label: str = "single sign-on"
    #: When set, the token must carry one of these values in ``groups_claim``.
    allowed_groups: list[str] = Field(default_factory=lambda: [])
    groups_claim: str = "groups"
    #: Base URL of this application as the provider redirects to it (default: as for CAS).
    public_url: str = ""
    #: CA bundle to verify the provider's certificate (empty: the system store).
    ca_cert_path: str = ""

    @model_validator(mode="after")
    def _check(self) -> OidcSettings:
        if self.client_secret and self.client_secret_file:
            raise ValueError("oidc: give client_secret or client_secret_file, not both")
        if self.client_secret_file:
            path = Path(self.client_secret_file)
            try:
                self.client_secret = path.read_text(encoding="utf-8").rstrip("\r\n")
            except OSError as exc:
                raise ValueError(f"oidc: cannot read client_secret_file: {exc}") from None
        if self.client_auth not in CLIENT_AUTH:
            raise ValueError(f"oidc.client_auth: one of {', '.join(CLIENT_AUTH)}")
        if self.enabled:
            if not self.issuer.startswith(("https://", "http://")):
                raise ValueError("oidc.issuer: an http(s) URL is required")
            if not self.client_id:
                raise ValueError("oidc.client_id is required")
            if self.client_auth != "none" and not self.client_secret:
                raise ValueError("oidc: a client secret is required (or client_auth: none)")
            if "openid" not in self.scopes:
                self.scopes = ["openid", *self.scopes]
        return self


@dataclass(frozen=True, slots=True)
class Provider:
    """What the discovery document says about the provider."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str = ""


# -- PKCE, state, nonce ---------------------------------------------------------------------------
def new_secret() -> str:
    """A random value for ``state``, ``nonce`` or the PKCE verifier (256 bits)."""
    return secrets.token_urlsafe(32)


def code_challenge(verifier: str) -> str:
    """S256 challenge of a PKCE verifier (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# -- pending logins -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Pending:
    """A sign-in between the redirect to the provider and its callback."""

    state: str
    nonce: str
    verifier: str
    directory_id: str
    next_path: str
    created_at: float


class PendingStore(Protocol):
    def add(self, pending: Pending) -> None: ...

    def take(self, state: str, now: float) -> Pending | None:
        """Remove and return the pending login ``state`` if it is still usable."""
        ...


class MemoryPendingStore:
    """For a single process without an application database (tests, demo)."""

    def __init__(self) -> None:
        self._items: dict[str, Pending] = {}
        self._lock = threading.Lock()

    def add(self, pending: Pending) -> None:
        with self._lock:
            now = pending.created_at
            for key in [k for k, p in self._items.items() if now - p.created_at > PENDING_SECONDS]:
                del self._items[key]
            self._items[pending.state] = pending

    def take(self, state: str, now: float) -> Pending | None:
        with self._lock:
            pending = self._items.pop(state, None)
        if pending is None or now - pending.created_at > PENDING_SECONDS:
            return None
        return pending


COMPONENT = "oidc"
#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE oidc_pending (
        state TEXT PRIMARY KEY,
        nonce TEXT NOT NULL,
        verifier TEXT NOT NULL,
        directory_id TEXT NOT NULL,
        next_path TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX oidc_pending_created_at ON oidc_pending (created_at);
    """,
)


class SqlPendingStore:
    """Pending logins in the application database: the callback may reach another replica."""

    def __init__(self, database: Database) -> None:
        self._db = database
        database.migrate(COMPONENT, MIGRATIONS)

    def add(self, pending: Pending) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM oidc_pending WHERE created_at < ?",
                (pending.created_at - PENDING_SECONDS,),
            )
            conn.execute(
                "INSERT INTO oidc_pending (state, nonce, verifier, directory_id, next_path,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    pending.state,
                    pending.nonce,
                    pending.verifier,
                    pending.directory_id,
                    pending.next_path,
                    pending.created_at,
                ),
            )

    def take(self, state: str, now: float) -> Pending | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT state, nonce, verifier, directory_id, next_path, created_at"
                " FROM oidc_pending WHERE state = ?",
                (state,),
            ).fetchone()
            if row is None:
                return None
            cur = conn.execute("DELETE FROM oidc_pending WHERE state = ?", (state,))
            if not cur.rowcount:
                return None  # another request took it first
        pending = Pending(
            row["state"],
            row["nonce"],
            row["verifier"],
            row["directory_id"],
            row["next_path"],
            float(row["created_at"]),
        )
        return None if now - pending.created_at > PENDING_SECONDS else pending


# -- the provider ---------------------------------------------------------------------------------
class OidcClient:
    """Talks to one provider: discovery, keys, code exchange, ID token checks."""

    def __init__(
        self,
        settings: OidcSettings,
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._clock = clock
        self._lock = threading.Lock()
        self._provider: tuple[float, Provider] | None = None
        self._keys: tuple[float, list[dict[str, Any]]] | None = None

    def _http(self) -> httpx2.Client:
        verify: Any = self.settings.ca_cert_path or True
        return httpx2.Client(transport=self._transport, timeout=10.0, verify=verify)

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            with self._http() as http:
                answer = http.get(url, headers={"Accept": "application/json"})
        except httpx2.HTTPError as exc:
            raise OidcError(f"provider unreachable: {type(exc).__name__}") from None
        if answer.status_code != 200:
            raise OidcError(f"{url}: HTTP {answer.status_code}")
        try:
            body: object = answer.json()
        except ValueError:
            raise OidcError(f"{url}: not JSON") from None
        if not isinstance(body, dict):
            raise OidcError(f"{url}: not a JSON object")
        return cast("dict[str, Any]", body)

    def provider(self) -> Provider:
        """The discovery document (cached for :data:`CACHE_SECONDS`)."""
        now = self._clock()
        with self._lock:
            cached = self._provider
        if cached is not None and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        issuer = self.settings.issuer.rstrip("/")
        doc = self._get_json(f"{issuer}/.well-known/openid-configuration")
        if str(doc.get("issuer", "")).rstrip("/") != issuer:
            raise OidcError("the discovery document names another issuer")
        methods = doc.get("code_challenge_methods_supported")
        if isinstance(methods, list) and "S256" not in methods:
            raise OidcError("the provider does not support PKCE with S256")
        try:
            found = Provider(
                issuer=str(doc["issuer"]),
                authorization_endpoint=str(doc["authorization_endpoint"]),
                token_endpoint=str(doc["token_endpoint"]),
                jwks_uri=str(doc["jwks_uri"]),
                end_session_endpoint=str(doc.get("end_session_endpoint") or ""),
            )
        except KeyError as exc:
            raise OidcError(f"the discovery document lacks {exc}") from None
        with self._lock:
            self._provider = (now, found)
        return found

    def _jwks(self, *, refresh: bool) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            cached = self._keys
        if cached is not None:
            fresh = now - cached[0] < CACHE_SECONDS
            recent = now - cached[0] < REFETCH_SECONDS
            if (fresh and not refresh) or recent:
                return cached[1]
        doc = self._get_json(self.provider().jwks_uri)
        raw = doc.get("keys")
        keys = (
            [cast("dict[str, Any]", k) for k in cast("list[object]", raw) if isinstance(k, dict)]
            if isinstance(raw, list)
            else []
        )
        with self._lock:
            self._keys = (now, keys)
        return keys

    def authorization_url(self, redirect_uri: str, state: str, nonce: str, verifier: str) -> str:
        query = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(dict.fromkeys(self.settings.scopes)),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        endpoint = self.provider().authorization_endpoint
        return f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(query)}"

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        """Trade the authorization code for tokens; returns the ID token."""
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        headers = {"Accept": "application/json"}
        if self.settings.client_auth == "client_secret_basic":
            client = _form_encode(self.settings.client_id)
            pair = f"{client}:{_form_encode(self.settings.client_secret)}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode("ascii")
        else:
            form["client_id"] = self.settings.client_id
            if self.settings.client_auth == "client_secret_post":
                form["client_secret"] = self.settings.client_secret
        try:
            with self._http() as http:
                answer = http.post(
                    self.provider().token_endpoint,
                    data=form,
                    headers=headers,
                )
        except httpx2.HTTPError as exc:
            raise OidcError(f"token endpoint unreachable: {type(exc).__name__}") from None
        if answer.status_code != 200:
            raise OidcError(f"token endpoint: HTTP {answer.status_code}")
        try:
            body: object = answer.json()
        except ValueError:
            raise OidcError("token endpoint: not JSON") from None
        token = cast("dict[str, Any]", body).get("id_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise OidcError("the token response has no id_token")
        return token

    def verify(self, id_token: str, nonce: str) -> dict[str, Any]:
        """The claims of a valid ID token for this client and ``nonce``."""
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise OidcError("malformed ID token") from None
        alg = str(header.get("alg", ""))
        if alg not in ALGORITHMS:
            raise OidcError(f"ID token algorithm refused: {alg or 'none'}")
        key = self._key_for(header)
        provider = self.provider()
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key,
                algorithms=[alg],
                audience=self.settings.client_id,
                issuer=provider.issuer,
                leeway=LEEWAY,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError(f"ID token refused: {type(exc).__name__}") from None
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("ID token nonce mismatch")
        several = len(claim_values(claims, "aud")) > 1
        if several and claims.get("azp") != self.settings.client_id:
            raise OidcError("ID token for several audiences without this client as azp")
        return claims

    def _key_for(self, header: Mapping[str, Any]) -> Any:
        kid = header.get("kid")
        for refresh in (False, True):
            keys = self._jwks(refresh=refresh)
            candidates = [
                k
                for k in keys
                if (kid is None or k.get("kid") == kid)
                and k.get("use", "sig") == "sig"
                and k.get("kty") in ("RSA", "EC")
            ]
            if len(candidates) == 1 or (kid is not None and candidates):
                try:
                    return jwt.PyJWK(candidates[0]).key
                except jwt.PyJWTError:
                    raise OidcError("unusable signing key") from None
        raise OidcError("no signing key for this ID token")

    def logout_url(self, id_token: str, post_logout_redirect_uri: str) -> str | None:
        """Where to end the provider's session (``None``: it has no end-session endpoint)."""
        try:
            endpoint = self.provider().end_session_endpoint
        except OidcError:
            return None
        if not endpoint:
            return None
        query = {
            "client_id": self.settings.client_id,
            "post_logout_redirect_uri": post_logout_redirect_uri,
        }
        if id_token:
            query["id_token_hint"] = id_token
        return f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(query)}"


def _form_encode(value: str) -> str:
    """Client credentials in HTTP Basic are form-encoded first (RFC 6749, 2.3.1)."""
    return quote_plus(value, safe="")


def claim_values(claims: Mapping[str, Any], name: str) -> list[str]:
    """A claim as a list of strings (a single value, a list, absent)."""
    value = claims.get(name)
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(v) for v in cast("Sequence[object]", value) if isinstance(v, (str, int))]
    return []


def unverified_claims(id_token: str) -> dict[str, Any]:
    """The payload of a token already verified (to read ``sid`` and such at logout)."""
    try:
        part = id_token.split(".")[1]
        padded = part + "=" * (-len(part) % 4)
        value: object = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError):
        return {}
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


__all__ = [
    "ALGORITHMS",
    "MemoryPendingStore",
    "OidcClient",
    "OidcError",
    "OidcSettings",
    "Pending",
    "PendingStore",
    "Provider",
    "SqlPendingStore",
    "claim_values",
    "code_challenge",
    "new_secret",
]
