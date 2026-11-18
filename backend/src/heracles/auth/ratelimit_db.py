"""Login rate limiter whose state lives in the application database.

Same policy as :class:`heracles.auth.ratelimit.RateLimiter`, but the counters are
shared by every worker process that opens the same database file, so an attacker
cannot multiply the allowed attempts by spreading them over workers. The clock is
the wall clock for the same reason: a monotonic clock is not comparable between
processes.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any

from heracles.auth.ratelimit import (
    DEFAULT_IP_FREE_ATTEMPTS,
    DEFAULT_LOGIN_FREE_ATTEMPTS,
    aggregate_keys,
)
from heracles.storage import Database

COMPONENT = "ratelimit"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE ratelimit_failures (
        key TEXT PRIMARY KEY,
        failures INTEGER NOT NULL,
        blocked_until REAL NOT NULL,
        last_failure REAL NOT NULL
    );
    CREATE INDEX ratelimit_failures_last ON ratelimit_failures (last_failure);
    """,
)

# 2**1000 still fits a float; beyond that the delay is capped by ``max_delay`` anyway.
_MAX_EXPONENT = 1000


class SqliteRateLimiter:
    """Block a key after ``free_attempts`` failures, doubling the delay each time."""

    def __init__(
        self,
        database: Database,
        *,
        free_attempts: int = 5,
        base_delay: float = 2.0,
        max_delay: float = 900.0,
        forget_after: float = 3600.0,
        max_entries: int = 10_000,
        ip_free_attempts: int = DEFAULT_IP_FREE_ATTEMPTS,
        login_free_attempts: int = DEFAULT_LOGIN_FREE_ATTEMPTS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ip_free = ip_free_attempts
        self._login_free = login_free_attempts
        self._db = database
        self._free = free_attempts
        self._base = base_delay
        self._max = max_delay
        self._forget = forget_after
        self._max_entries = max_entries
        self._clock = clock
        database.migrate(COMPONENT, MIGRATIONS)

    @staticmethod
    def key(ip: str, login: str) -> str:
        return f"{ip}|{login.strip().lower()}"

    def retry_after(self, key: str) -> float:
        """Seconds the caller must wait (0 when allowed)."""
        now = self._clock()
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT blocked_until, last_failure FROM ratelimit_failures WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None or now - row["last_failure"] > self._forget:
            return 0.0
        return max(0.0, row["blocked_until"] - now)

    def record_failure(self, key: str) -> None:
        now = self._clock()
        # One write transaction (BEGIN IMMEDIATE): concurrent workers cannot lose an increment.
        with self._db.transaction() as conn:
            # Opportunistic purge on the write path, so the table follows the traffic and
            # a forgotten key also restarts from zero failures.
            conn.execute(
                "DELETE FROM ratelimit_failures WHERE last_failure < ?", (now - self._forget,)
            )
            self._count_failure(conn, key, now, self._free)

    def attempt(self, key: str) -> float:
        """Check the key and count the attempt in one transaction (see ``LoginLimiter``).

        Same policy as the in-memory limiter: pair, address and login counters; a key that
        cannot be tracked because the table is full of active blocks is refused.
        """
        now = self._clock()
        counters = [(key, self._free), *aggregate_keys(key, self._ip_free, self._login_free)]
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM ratelimit_failures WHERE last_failure < ?", (now - self._forget,)
            )
            wait = 0.0
            for name, _ in counters:
                row = conn.execute(
                    "SELECT blocked_until FROM ratelimit_failures WHERE key = ?", (name,)
                ).fetchone()
                if row is not None:
                    wait = max(wait, float(row["blocked_until"]) - now)
            if wait > 0:
                return wait
            for name, free in counters:
                if not self._count_failure(conn, name, now, free):
                    row = conn.execute(
                        "SELECT MIN(blocked_until) FROM ratelimit_failures"
                    ).fetchone()
                    return max(1.0, float(row[0]) - now)
            return 0.0

    def _count_failure(self, conn: Any, key: str, now: float, free: int) -> bool:
        """Count one failure of ``key`` in the caller's transaction; False when untrackable."""
        row = conn.execute(
            "SELECT failures FROM ratelimit_failures WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            if not self._make_room(conn, now):
                return False
            failures = 1
        else:
            failures = int(row["failures"]) + 1
        over = failures - free
        blocked_until = 0.0
        if over >= 0:
            delay = min(self._max, self._base * (2 ** min(over, _MAX_EXPONENT)))
            blocked_until = now + delay
        conn.execute(
            "INSERT INTO ratelimit_failures (key, failures, blocked_until, last_failure)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET failures = excluded.failures,"
            " blocked_until = excluded.blocked_until,"
            " last_failure = excluded.last_failure",
            (key, failures, blocked_until, now),
        )
        return True

    def record_success(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM ratelimit_failures WHERE key = ?", (key,))

    def _make_room(self, conn: sqlite3.Connection, now: float) -> bool:
        """Drop the oldest tenth of the unblocked entries when the (purged) table is full.

        Keys are chosen by the client (an address and a login name), so the table must not
        grow with the attacker's imagination. An entry whose block is still running is never
        evicted, or filling the table with made-up logins would erase it. Returns False when
        no room could be made.
        """
        row = conn.execute("SELECT COUNT(*) FROM ratelimit_failures").fetchone()
        if int(row[0]) < self._max_entries:
            return True
        conn.execute(
            "DELETE FROM ratelimit_failures WHERE key IN ("
            " SELECT key FROM ratelimit_failures WHERE blocked_until <= ?"
            " ORDER BY last_failure LIMIT ?)",
            (now, max(1, self._max_entries // 10)),
        )
        row = conn.execute("SELECT COUNT(*) FROM ratelimit_failures").fetchone()
        return int(row[0]) < self._max_entries
