"""Login rate limiting with exponential backoff (in-memory; see ``ratelimit_db`` for shared)."""

from __future__ import annotations

import contextlib
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

    def attempt(self, key: str) -> float:
        """Atomically check the key and count one attempt: seconds to wait, 0 to go ahead.

        The attempt is counted before the credentials are checked, so a burst of parallel
        requests cannot all pass the check; a successful sign-in calls :meth:`record_success`.
        """
        ...

    def record_failure(self, key: str) -> None: ...

    def record_success(self, key: str) -> None: ...


#: Attempts tolerated per hour from one address / against one login, across every
#: ``address|login`` pair, before the same backoff applies to the aggregate (0 disables it).
#: Far above the per-pair allowance, so that a shared address or an ordinary user never
#: reaches it, while a spray over many logins or accounts does.
DEFAULT_IP_FREE_ATTEMPTS = 300
DEFAULT_LOGIN_FREE_ATTEMPTS = 30


def aggregate_keys(key: str, ip_free: int, login_free: int) -> list[tuple[str, int]]:
    """The aggregate counters (key, free attempts) an ``address|login`` key feeds.

    The ``@`` prefix cannot start an address, so aggregates never collide with pair keys.
    """
    ip, sep, login = key.partition("|")
    if not sep:
        return []
    found: list[tuple[str, int]] = []
    if ip_free > 0:
        found.append((f"@ip:{ip}", ip_free))
    if login_free > 0:
        found.append((f"@login:{login}", login_free))
    return found


class _FullError(Exception):
    """The table holds only active blocks: a new key cannot be tracked."""


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
        ip_free_attempts: int = DEFAULT_IP_FREE_ATTEMPTS,
        login_free_attempts: int = DEFAULT_LOGIN_FREE_ATTEMPTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._free = free_attempts
        self._ip_free = ip_free_attempts
        self._login_free = login_free_attempts
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

    def attempt(self, key: str) -> float:
        """Check the key and count the attempt in one locked step (see :class:`LoginLimiter`).

        The pair, its address and its login are all checked and counted. When the table is
        full of active blocks, a key that is not tracked yet is refused (fail closed) until
        the earliest block ends: evicting a block would let an attacker erase their own.
        """
        now = self._clock()
        counters = [(key, self._free), *aggregate_keys(key, self._ip_free, self._login_free)]
        with self._lock:
            wait = 0.0
            for name, _ in counters:
                entry = self._entries.get(name)
                if entry is not None and now - entry.last_failure > self._forget:
                    del self._entries[name]
                    entry = None
                if entry is not None:
                    wait = max(wait, entry.blocked_until - now)
            if wait > 0:
                return wait
            try:
                for name, free in counters:
                    self._count_failure(name, now, free)
            except _FullError:
                return self._earliest_unblock(now)
            return 0.0

    def record_failure(self, key: str) -> None:
        now = self._clock()
        # attempt() refuses what cannot be tracked, so a full table is ignored here.
        with self._lock, contextlib.suppress(_FullError):
            self._count_failure(key, now, self._free)

    def _count_failure(self, key: str, now: float, free: int) -> None:
        """Count one failure of ``key``; the caller holds the lock."""
        if key not in self._entries and len(self._entries) >= self._max_entries:
            self._make_room(now)
            if len(self._entries) >= self._max_entries:
                raise _FullError
        entry = self._entries.setdefault(key, _Entry())
        entry.failures += 1
        entry.last_failure = now
        over = entry.failures - free
        if over >= 0:
            entry.blocked_until = now + min(self._max, self._base * (2**over))

    def record_success(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _earliest_unblock(self, now: float) -> float:
        return max(1.0, min(e.blocked_until for e in self._entries.values()) - now)

    def _make_room(self, now: float) -> None:
        """Drop the expired entries, then the oldest tenth of the unblocked ones.

        Keys are chosen by the client (an address and a login name), so the table must not
        grow with the attacker's imagination. An entry whose block is still running is never
        evicted: otherwise filling the table with failures on made-up logins would erase it.
        """
        stale = [k for k, e in self._entries.items() if now - e.last_failure > self._forget]
        for k in stale:
            del self._entries[k]
        if len(self._entries) >= self._max_entries:
            free = [k for k, e in self._entries.items() if e.blocked_until <= now]
            free.sort(key=lambda k: self._entries[k].last_failure)
            for k in free[: max(1, self._max_entries // 10)]:
                del self._entries[k]
