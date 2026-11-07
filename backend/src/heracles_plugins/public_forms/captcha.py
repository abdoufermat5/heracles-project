"""Stateless arithmetic challenge for public forms.

The challenge token is ``base64(payload).signature``; the payload carries the
operands, an expiry and a nonce, signed with a server secret. A solved token can
be used only once (the nonce is remembered until it expires).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any


class Captcha:
    """Create and verify challenges."""

    def __init__(
        self,
        secret: bytes | None = None,
        *,
        ttl: float = 600.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._ttl = ttl
        self._clock = clock
        self._used: dict[str, float] = {}
        self._lock = threading.Lock()

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def new_challenge(self) -> dict[str, str]:
        """``{"question": "3 + 9", "token": ...}``."""
        a, b = secrets.randbelow(10) + 1, secrets.randbelow(10) + 1
        payload = json.dumps(
            {"a": a, "b": b, "e": self._clock() + self._ttl, "n": secrets.token_hex(8)},
            separators=(",", ":"),
        ).encode()
        token = base64.urlsafe_b64encode(payload).decode() + "." + self._sign(payload)
        return {"question": f"{a} + {b}", "token": token}

    def verify(self, token: str | None, answer: str | None) -> bool:
        """True if ``answer`` solves the (unexpired, unused) challenge ``token``."""
        if not token or answer is None:
            return False
        body, _sep, signature = token.partition(".")
        try:
            payload = base64.urlsafe_b64decode(body.encode())
        except (binascii.Error, ValueError):
            return False
        if not hmac.compare_digest(signature, self._sign(payload)):
            return False
        try:
            data: dict[str, Any] = json.loads(payload)
            expected = int(data["a"]) + int(data["b"])
            expires = float(data["e"])
            nonce = str(data["n"])
        except (ValueError, KeyError, TypeError):
            return False
        now = self._clock()
        if now > expires or answer.strip() != str(expected):
            return False
        with self._lock:
            self._used = {n: e for n, e in self._used.items() if e > now}
            if nonce in self._used:
                return False
            self._used[nonce] = expires
        return True
