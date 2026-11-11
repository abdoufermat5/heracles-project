"""Login rate limiting with exponential backoff (in-memory; see ``ratelimit_db`` for shared)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class LoginLimiter(Protocol):
    """What the login flow needs from a rate limiter (per-process or shared)."""

    def key(self, ip: str, login: str) -> str:
        """The throttling key of an attempt."""
        ...

    def retry_after(self, key: str) -> float:
        """Seconds the caller must wait (0 when allowed)."""
        ...

    def record_failure(self, key: str) -> None: ...

    def record_success(self, key: str) -> None: ...


@dataclass(slots=True)
class _Entry:
    failures: int = 0
    blocked_until: float = 0.0
    last_failure: float = 0.0


class RateLimiter:
    """Block a key after ``free_attempts`` failures, doubling the delay each time."""

    def __init__(
        self,
        *,
        free_attempts: int = 5,
        base_delay: float = 2.0,
        max_delay: float = 900.0,
        forget_after: float = 3600.0,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._free = free_attempts
        self._base = base_delay
        self._max = max_delay
        self._forget = forget_after
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(ip: str, login: str) -> str:
        return f"{ip}|{login.strip().lower()}"

    def retry_after(self, key: str) -> float:
        """Seconds the caller must wait (0 when allowed)."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return 0.0
            if now - entry.last_failure > self._forget:
                del self._entries[key]
                return 0.0
            return max(0.0, entry.blocked_until - now)

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            if key not in self._entries and len(self._entries) >= self._max_entries:
                self._make_room(now)
            entry = self._entries.setdefault(key, _Entry())
            entry.failures += 1
            entry.last_failure = now
            over = entry.failures - self._free
            if over >= 0:
                entry.blocked_until = now + min(self._max, self._base * (2**over))

    def record_success(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _make_room(self, now: float) -> None:
        """Drop the expired entries, then the oldest tenth when the table is still full.

        Keys are chosen by the client (an address and a login name), so the table must not
        grow with the attacker's imagination.
        """
        stale = [k for k, e in self._entries.items() if now - e.last_failure > self._forget]
        for k in stale:
            del self._entries[k]
        if len(self._entries) >= self._max_entries:
            oldest = sorted(self._entries, key=lambda k: self._entries[k].last_failure)
            for k in oldest[: max(1, self._max_entries // 10)]:
                del self._entries[k]
