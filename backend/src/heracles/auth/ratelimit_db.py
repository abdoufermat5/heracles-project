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
        clock: Callable[[], float] = time.time,
    ) -> None:
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
            self._count_failure(conn, key, now)

    def attempt(self, key: str) -> float:
        """Check the key and count the attempt in one transaction (see ``LoginLimiter``)."""
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM ratelimit_failures WHERE last_failure < ?", (now - self._forget,)
            )
            row = conn.execute(
                "SELECT blocked_until FROM ratelimit_failures WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                wait = max(0.0, float(row["blocked_until"]) - now)
                if wait > 0:
                    return wait
            self._count_failure(conn, key, now)
            return 0.0

    def _count_failure(self, conn: Any, key: str, now: float) -> None:
        """Count one failure of ``key`` inside the caller's transaction."""
        row = conn.execute(
            "SELECT failures FROM ratelimit_failures WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            self._make_room(conn)
            failures = 1
        else:
            failures = int(row["failures"]) + 1
        over = failures - self._free
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

    def record_success(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM ratelimit_failures WHERE key = ?", (key,))

    def _make_room(self, conn: sqlite3.Connection) -> None:
        """Drop the oldest tenth when the (already purged) table is still full.

        Keys are chosen by the client (an address and a login name), so the table must not
        grow with the attacker's imagination.
        """
        row = conn.execute("SELECT COUNT(*) FROM ratelimit_failures").fetchone()
        if int(row[0]) < self._max_entries:
            return
        conn.execute(
            "DELETE FROM ratelimit_failures WHERE key IN ("
            " SELECT key FROM ratelimit_failures ORDER BY last_failure LIMIT ?)",
            (max(1, self._max_entries // 10),),
        )
