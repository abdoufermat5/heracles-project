"""In-memory login rate limiter with exponential backoff."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._free = free_attempts
        self._base = base_delay
        self._max = max_delay
        self._forget = forget_after
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
            if len(self._entries) > 10_000:
                self._purge(now)
            entry = self._entries.setdefault(key, _Entry())
            entry.failures += 1
            entry.last_failure = now
            over = entry.failures - self._free
            if over >= 0:
                entry.blocked_until = now + min(self._max, self._base * (2**over))

    def record_success(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _purge(self, now: float) -> None:
        stale = [k for k, e in self._entries.items() if now - e.last_failure > self._forget]
        for k in stale:
            del self._entries[k]
