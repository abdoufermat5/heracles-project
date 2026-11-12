"""State of the public forms shared by every server process (replicas on several hosts).

The challenge secret, the single-use nonces and the per-address submission window live in
the application database, so a challenge issued by one replica verifies on another, a
solved challenge cannot be replayed on a second replica, and the submission limit is not
multiplied by the number of replicas. Plain ANSI SQL with the ``?`` placeholders of
:class:`heracles.storage.Database`.
"""

from __future__ import annotations

import contextlib
import secrets
import time
from collections.abc import Callable

from heracles.storage import Database

COMPONENT = "public_forms"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE public_forms_nonces (
        nonce TEXT PRIMARY KEY,
        expires REAL NOT NULL
    );
    CREATE INDEX public_forms_nonces_expires ON public_forms_nonces (expires);
    CREATE TABLE public_forms_events (
        key TEXT NOT NULL,
        at REAL NOT NULL
    );
    CREATE INDEX public_forms_events_key ON public_forms_events (key, at);
    CREATE TABLE public_forms_secret (
        id INTEGER PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
)


def prepare(database: Database) -> None:
    database.migrate(COMPONENT, MIGRATIONS)


def load_secret(database: Database) -> bytes:
    """The signing secret shared by all replicas (generated once, kept in the database)."""
    prepare(database)
    for _attempt in range(2):
        with database.connection() as conn:
            row = conn.execute("SELECT value FROM public_forms_secret WHERE id = 1").fetchone()
        if row is not None:
            return bytes.fromhex(str(row[0]))
        # A concurrent replica may insert first (primary key): then the next pass reads it.
        with contextlib.suppress(Exception), database.transaction() as conn:
            conn.execute(
                "INSERT INTO public_forms_secret (id, value) VALUES (1, ?)",
                (secrets.token_hex(32),),
            )
    raise RuntimeError("cannot load the public forms secret")


class DbNonceStore:
    """Single-use nonces: the first replica to insert a nonce wins."""

    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = database
        self._clock = clock
        prepare(database)

    def claim(self, nonce: str, expires: float) -> bool:
        now = self._clock()
        try:
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM public_forms_nonces WHERE expires < ?", (now,))
                conn.execute(
                    "INSERT INTO public_forms_nonces (nonce, expires) VALUES (?, ?)",
                    (nonce, expires),
                )
        except Exception:
            return False
        return True


class DbSubmissionWindow:
    """At most ``limit`` events per key in a sliding window, counted in the database."""

    def __init__(
        self,
        database: Database,
        limit: int,
        window: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db = database
        self._limit = limit
        self._window = window
        self._clock = clock
        prepare(database)

    def retry_after(self, key: str) -> float:
        now = self._clock()
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT at FROM public_forms_events WHERE key = ? AND at > ? ORDER BY at",
                (key, now - self._window),
            ).fetchall()
        if len(rows) < self._limit:
            return 0.0
        oldest = float(rows[len(rows) - self._limit][0])
        return max(0.0, self._window - (now - oldest))

    def record(self, key: str) -> None:
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM public_forms_events WHERE at < ?", (now - self._window,))
            conn.execute("INSERT INTO public_forms_events (key, at) VALUES (?, ?)", (key, now))
