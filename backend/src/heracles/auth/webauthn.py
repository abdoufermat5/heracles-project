"""WebAuthn registration / assertion service (skeleton; UI comes later).

Challenges are returned to the caller, which keeps them in the session cache.
Credentials are persisted through :class:`~heracles.auth.second_factor.SecondFactorStore`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from heracles.auth.second_factor import SecondFactorStore, WebAuthnCredential


class WebAuthnError(Exception):
    """Registration or assertion failed."""


class WebAuthnSettings(BaseModel):
    rp_id: str = "localhost"
    rp_name: str = "Heracles"
    origin: str = "http://localhost:8000"


@dataclass(frozen=True, slots=True)
class WebAuthnChallenge:
    """Options for the browser plus the challenge the server must remember."""

    options: dict[str, Any]
    challenge: bytes


class WebAuthnService:
    def __init__(self, store: SecondFactorStore, settings: WebAuthnSettings) -> None:
        self._store = store
        self._settings = settings

    def _descriptors(self, user_dn: str) -> list[PublicKeyCredentialDescriptor]:
        return [
            PublicKeyCredentialDescriptor(id=c.credential_id)
            for c in self._store.webauthn_credentials(user_dn)
        ]

    def begin_registration(
        self, user_dn: str, user_name: str, display_name: str | None = None
    ) -> WebAuthnChallenge:
        options = generate_registration_options(
            rp_id=self._settings.rp_id,
            rp_name=self._settings.rp_name,
            user_name=user_name,
            user_display_name=display_name or user_name,
            exclude_credentials=self._descriptors(user_dn),
        )
        data = cast(dict[str, Any], json.loads(options_to_json(options)))
        return WebAuthnChallenge(data, options.challenge)

    def finish_registration(
        self, user_dn: str, credential: dict[str, Any], challenge: bytes, label: str = ""
    ) -> WebAuthnCredential:
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self._settings.rp_id,
                expected_origin=self._settings.origin,
            )
        except Exception as exc:
            raise WebAuthnError(str(exc)) from exc
        stored = WebAuthnCredential(
            verified.credential_id,
            verified.credential_public_key,
            verified.sign_count,
            label,
        )
        self._store.add_webauthn_credential(user_dn, stored)
        return stored

    def begin_assertion(self, user_dn: str) -> WebAuthnChallenge:
        options = generate_authentication_options(
            rp_id=self._settings.rp_id,
            allow_credentials=self._descriptors(user_dn),
        )
        data = cast(dict[str, Any], json.loads(options_to_json(options)))
        return WebAuthnChallenge(data, options.challenge)

    def finish_assertion(self, user_dn: str, credential: dict[str, Any], challenge: bytes) -> bool:
        try:
            raw_id = base64url_to_bytes(str(credential["rawId"]))
        except (KeyError, ValueError) as exc:
            raise WebAuthnError("malformed credential") from exc
        known = next(
            (c for c in self._store.webauthn_credentials(user_dn) if c.credential_id == raw_id),
            None,
        )
        if known is None:
            return False
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self._settings.rp_id,
                expected_origin=self._settings.origin,
                credential_public_key=known.public_key,
                credential_current_sign_count=known.sign_count,
            )
        except Exception as exc:
            raise WebAuthnError(str(exc)) from exc
        self._store.update_sign_count(user_dn, raw_id, verified.new_sign_count)
        return True
