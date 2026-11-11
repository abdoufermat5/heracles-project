"""Proof-of-work challenge for public forms (self-hosted, no image puzzle).

The server issues a signed ``{nonce, difficulty, issued, expiry}``; the client searches a
counter such that ``SHA-256("<nonce>:<counter>")`` starts with ``difficulty`` zero bits and
sends it back as the answer. The token is ``base64(payload).signature`` (HMAC-SHA-256 with a
server secret), so nothing has to be stored to issue a challenge; a solved token can be used
only once (the nonce is remembered until it expires) and not before ``min_fill_seconds`` after
it was issued (a form filled in faster than a person can is a script).
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

#: About 0.5 to 1 s of work in a browser worker (2**20 hashes on average).
DEFAULT_DIFFICULTY = 20
MAX_DIFFICULTY = 32
MIN_FILL_SECONDS = 3.0
_MAX_USED = 100_000


def leading_zero_bits(digest: bytes) -> int:
    """Number of zero bits at the start of ``digest``."""
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        return bits + (8 - byte.bit_length())
    return bits


def solve(nonce: str, difficulty: int) -> int:
    """Reference solver (tests and tooling; browsers use the worker of the frontend)."""
    counter = 0
    while leading_zero_bits(hashlib.sha256(f"{nonce}:{counter}".encode()).digest()) < difficulty:
        counter += 1
    return counter


class Captcha:
    """Create and verify challenges."""

    def __init__(
        self,
        secret: bytes | None = None,
        *,
        ttl: float = 600.0,
        difficulty: int = DEFAULT_DIFFICULTY,
        min_fill: float = MIN_FILL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._ttl = ttl
        self._difficulty = max(0, min(difficulty, MAX_DIFFICULTY))
        self._min_fill = min_fill
        self._clock = clock
        self._used: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def min_fill(self) -> float:
        return self._min_fill

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def new_challenge(self) -> dict[str, Any]:
        """``{"token", "nonce", "difficulty", "algorithm", "min_fill_seconds"}``."""
        now = self._clock()
        nonce = secrets.token_hex(16)
        payload = json.dumps(
            {"n": nonce, "d": self._difficulty, "i": now, "e": now + self._ttl},
            separators=(",", ":"),
        ).encode()
        return {
            "token": base64.urlsafe_b64encode(payload).decode() + "." + self._sign(payload),
            "nonce": nonce,
            "difficulty": self._difficulty,
            "algorithm": "sha256",
            "min_fill_seconds": self._min_fill,
        }

    def verify(self, token: str | None, answer: str | None) -> bool:
        """True if ``answer`` solves the (unexpired, unused, old enough) challenge ``token``."""
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
            nonce = str(data["n"])
            difficulty = int(data["d"])
            issued = float(data["i"])
            expires = float(data["e"])
        except (ValueError, KeyError, TypeError):
            return False
        counter = answer.strip()
        if not (counter.isascii() and counter.isdigit() and len(counter) <= 15):
            return False
        now = self._clock()
        if now > expires or now - issued < self._min_fill:
            return False
        digest = hashlib.sha256(f"{nonce}:{int(counter)}".encode()).digest()
        if leading_zero_bits(digest) < difficulty:
            return False
        with self._lock:
            self._used = {n: e for n, e in self._used.items() if e > now}
            if nonce in self._used or len(self._used) >= _MAX_USED:
                return False
            self._used[nonce] = expires
        return True
