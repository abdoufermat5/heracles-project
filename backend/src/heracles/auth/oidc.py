# pyright: basic
"""OpenID Connect login (authorization code + PKCE) — skeleton.

TODO: full implementation (discovery, token exchange, ID token validation,
claim -> login attribute mapping, session creation). Only the configuration
model and the PKCE / authorization URL plumbing exist today; the HTTP routes
return 501.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from authlib.common.security import generate_token
from authlib.integrations.httpx_client import OAuth2Client
from pydantic import BaseModel, Field


class OidcSettings(BaseModel):
    """OIDC provider configuration."""

    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    redirect_uri: str = ""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    #: ID-token claim whose value is looked up in the directory login attribute.
    login_claim: str = "preferred_username"


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


class OidcClient:
    """Builds authorization requests; the callback half is not implemented yet."""

    def __init__(self, settings: OidcSettings) -> None:
        self.settings = settings

    def begin(self) -> AuthorizationRequest:
        s = self.settings
        verifier = generate_token(48)
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        client = OAuth2Client(
            client_id=s.client_id,
            client_secret=s.client_secret,
            scope=" ".join(s.scopes),
            redirect_uri=s.redirect_uri,
            code_challenge_method="S256",
        )
        url, _ = client.create_authorization_url(
            s.authorization_endpoint,
            state=state,
            nonce=nonce,
            code_verifier=verifier,
        )
        return AuthorizationRequest(str(url), state, nonce, verifier)

    def complete(self, code: str, state: str) -> str:
        """Exchange the code and return the login (not implemented)."""
        raise NotImplementedError("OIDC callback is not implemented yet")
