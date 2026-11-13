"""Password-recovery tokens stored in the application database.

Shared by every worker process, so a link requested on one worker can be confirmed
on another, and a token can still be used only once.
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable

from heracles.auth.recovery import TokenRecord
from heracles.ldap import dn as dnlib
from heracles.storage import Database

COMPONENT = "recovery_tokens"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE recovery_tokens (
        user_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (user_key, kind)
    );
    """,
)


class SqliteTokenStore:
    """:class:`~heracles.auth.recovery.TokenStore` on the application database.

    One token per (normalised user DN, kind), like the in-memory store.
    """

    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = database
        self._clock = clock
        database.migrate(COMPONENT, MIGRATIONS)

    def put(self, record: TokenRecord) -> None:
        key = dnlib.normalize(record.user_dn)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO recovery_tokens (user_key, kind, token_hash, created_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (user_key, kind) DO UPDATE SET"
                " token_hash = excluded.token_hash, created_at = excluded.created_at",
                (key, record.kind, record.token_hash, record.created_at),
            )

    def valid(self, user_dn: str, token_hash: str, *, kind: str, max_age: float) -> bool:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT token_hash, created_at FROM recovery_tokens"
                " WHERE user_key = ? AND kind = ?",
                (dnlib.normalize(user_dn), kind),
            ).fetchone()
        return (
            row is not None
            and self._clock() - row["created_at"] <= max_age
            and hmac.compare_digest(row["token_hash"], token_hash)
        )

    def consume(self, user_dn: str, token_hash: str, *, kind: str, max_age: float) -> bool:
        key = dnlib.normalize(user_dn)
        # BEGIN IMMEDIATE serialises the read and the delete across processes, so of
        # several concurrent consumers exactly one sees the row.
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT token_hash, created_at FROM recovery_tokens"
                " WHERE user_key = ? AND kind = ?",
                (key, kind),
            ).fetchone()
            if row is None:
                return False
            expired = self._clock() - row["created_at"] > max_age
            if not expired and not hmac.compare_digest(row["token_hash"], token_hash):
                return False  # a wrong guess must not burn the user's valid token
            conn.execute("DELETE FROM recovery_tokens WHERE user_key = ? AND kind = ?", (key, kind))
            return not expired
