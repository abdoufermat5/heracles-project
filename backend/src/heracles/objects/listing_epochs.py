"""Per-session change counters in the application database.

The listing snapshots (:mod:`heracles.objects.listing_cache`) live in the memory of each
server process. With several replicas, a write served by replica A must also invalidate the
snapshots that replica B holds for the same session. Every mutating request bumps the
counter of its session (one small upsert); a snapshot records the counter it was made under
and is ignored once the counter moved. Reading the counter is one primary-key lookup, done
at most once per request.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable

from heracles.storage import Database

COMPONENT = "listing_epochs"
#: Counters untouched for this long are dropped (their session is long gone).
KEEP_SECONDS = 86_400.0
#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE listing_epochs (
        owner TEXT PRIMARY KEY,
        epoch INTEGER NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX listing_epochs_updated ON listing_epochs (updated_at);
    """,
)


def _key(session_id: str) -> str:
    # never store the raw session id
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class ListingEpochs:
    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = database
        self._clock = clock
        database.migrate(COMPONENT, MIGRATIONS)

    def current(self, session_id: str) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT epoch FROM listing_epochs WHERE owner = ?", (_key(session_id),)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def bump(self, session_id: str) -> None:
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO listing_epochs (owner, epoch, updated_at) VALUES (?, 1, ?)"
                " ON CONFLICT (owner) DO UPDATE SET epoch = listing_epochs.epoch + 1,"
                " updated_at = excluded.updated_at",
                (_key(session_id), now),
            )
            conn.execute("DELETE FROM listing_epochs WHERE updated_at < ?", (now - KEEP_SECONDS,))
