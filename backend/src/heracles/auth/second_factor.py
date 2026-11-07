"""Second factor: TOTP (RFC 6238, +-1 step) and single-use recovery codes."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import pyotp

from heracles.ldap import dn as dnlib

TOTP_STEP_SECONDS = 30
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True, slots=True)
class WebAuthnCredential:
    """A registered WebAuthn authenticator."""

    credential_id: bytes
    public_key: bytes
    sign_count: int
    label: str = ""


class SecondFactorStore(Protocol):
    """Persistence of a user's second-factor registrations."""

    def totp_secret(self, user_dn: str) -> str | None: ...
    def set_totp_secret(self, user_dn: str, secret: str | None) -> None: ...
    def last_totp_step(self, user_dn: str) -> int: ...
    def set_last_totp_step(self, user_dn: str, step: int) -> None: ...
    def recovery_hashes(self, user_dn: str) -> list[str]: ...
    def set_recovery_hashes(self, user_dn: str, hashes: list[str]) -> None: ...
    def consume_recovery_hash(self, user_dn: str, digest: str) -> bool:
        """Atomically remove ``digest``; True if it was present."""
        ...

    def webauthn_credentials(self, user_dn: str) -> list[WebAuthnCredential]: ...
    def add_webauthn_credential(self, user_dn: str, credential: WebAuthnCredential) -> None: ...
    def update_sign_count(self, user_dn: str, credential_id: bytes, sign_count: int) -> None: ...


class InMemorySecondFactorStore:
    """Process-local store for development and tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totp: dict[str, str] = {}
        self._steps: dict[str, int] = {}
        self._recovery: dict[str, list[str]] = {}
        self._webauthn: dict[str, list[WebAuthnCredential]] = {}

    @staticmethod
    def _k(user_dn: str) -> str:
        return dnlib.normalize(user_dn)

    def totp_secret(self, user_dn: str) -> str | None:
        return self._totp.get(self._k(user_dn))

    def set_totp_secret(self, user_dn: str, secret: str | None) -> None:
        with self._lock:
            if secret is None:
                self._totp.pop(self._k(user_dn), None)
            else:
                self._totp[self._k(user_dn)] = secret

    def last_totp_step(self, user_dn: str) -> int:
        return self._steps.get(self._k(user_dn), 0)

    def set_last_totp_step(self, user_dn: str, step: int) -> None:
        with self._lock:
            self._steps[self._k(user_dn)] = step

    def recovery_hashes(self, user_dn: str) -> list[str]:
        return list(self._recovery.get(self._k(user_dn), []))

    def set_recovery_hashes(self, user_dn: str, hashes: list[str]) -> None:
        with self._lock:
            self._recovery[self._k(user_dn)] = list(hashes)

    def consume_recovery_hash(self, user_dn: str, digest: str) -> bool:
        with self._lock:
            items = self._recovery.get(self._k(user_dn), [])
            if digest in items:
                items.remove(digest)
                return True
            return False

    def webauthn_credentials(self, user_dn: str) -> list[WebAuthnCredential]:
        return list(self._webauthn.get(self._k(user_dn), []))

    def add_webauthn_credential(self, user_dn: str, credential: WebAuthnCredential) -> None:
        with self._lock:
            self._webauthn.setdefault(self._k(user_dn), []).append(credential)

    def update_sign_count(self, user_dn: str, credential_id: bytes, sign_count: int) -> None:
        with self._lock:
            creds = self._webauthn.get(self._k(user_dn), [])
            for i, c in enumerate(creds):
                if c.credential_id == credential_id:
                    creds[i] = WebAuthnCredential(
                        c.credential_id, c.public_key, sign_count, c.label
                    )


def hash_recovery_code(code: str) -> str:
    """Hash of a recovery code (codes carry ~50 bits of entropy, so SHA-256 suffices)."""
    normalized = code.replace("-", "").replace(" ", "").upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_recovery_codes(count: int = 10) -> list[str]:
    """Human-friendly codes such as ``ABCDE-FGHJK``."""
    codes: list[str] = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


class SecondFactorService:
    """Registration and verification of TOTP and recovery codes."""

    def __init__(
        self,
        store: SecondFactorStore,
        *,
        issuer: str = "Heracles",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.issuer = issuer
        self._clock = clock

    # -- discovery ---------------------------------------------------------
    def methods_for(self, user_dn: str) -> list[str]:
        methods: list[str] = []
        if self.store.totp_secret(user_dn):
            methods.append("totp")
        if self.store.webauthn_credentials(user_dn):
            methods.append("webauthn")
        if methods and self.store.recovery_hashes(user_dn):
            methods.append("recovery")
        return methods

    # -- TOTP --------------------------------------------------------------
    def enroll_totp(self, user_dn: str, account_name: str) -> tuple[str, str]:
        """Create a secret; return ``(secret, otpauth_uri)``."""
        secret = pyotp.random_base32()
        self.store.set_totp_secret(user_dn, secret)
        uri = str(
            pyotp.TOTP(secret).provisioning_uri(  # pyright: ignore[reportUnknownMemberType]
                name=account_name, issuer_name=self.issuer
            )
        )
        return secret, uri

    def verify_totp(self, user_dn: str, code: str) -> bool:
        """Accept the current step +-1; a step is accepted only once."""
        secret = self.store.totp_secret(user_dn)
        code = code.strip().replace(" ", "")
        if not secret or not code.isdigit():
            return False
        totp = pyotp.TOTP(secret, interval=TOTP_STEP_SECONDS)
        now = self._clock()
        last = self.store.last_totp_step(user_dn)
        for offset in (0, -1, 1):
            at = now + offset * TOTP_STEP_SECONDS
            step = int(at // TOTP_STEP_SECONDS)
            if step > last and secrets.compare_digest(totp.at(int(at)), code):
                self.store.set_last_totp_step(user_dn, step)
                return True
        return False

    # -- recovery codes ----------------------------------------------------
    def regenerate_recovery_codes(self, user_dn: str, count: int = 10) -> list[str]:
        """Replace all codes; return the clear codes (shown once)."""
        codes = generate_recovery_codes(count)
        self.store.set_recovery_hashes(user_dn, [hash_recovery_code(c) for c in codes])
        return codes

    def verify_recovery(self, user_dn: str, code: str) -> bool:
        return self.store.consume_recovery_hash(user_dn, hash_recovery_code(code))

    # -- dispatch ----------------------------------------------------------
    def verify(self, user_dn: str, method: str, code: str) -> bool:
        if method == "totp":
            return self.verify_totp(user_dn, code)
        if method == "recovery":
            return self.verify_recovery(user_dn, code)
        return False
