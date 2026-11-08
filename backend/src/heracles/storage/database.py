"""The application's own SQLite database.

Heracles keeps the directory as the source of truth for objects; this database
holds the server-side state that has no place in the directory (second-factor
registrations first, more later). Every feature owns a *component* with its own
ordered list of migrations::

    db = Database(Path("/var/lib/heracles/heracles.db"))
    db.migrate("second_factor", SECOND_FACTOR_MIGRATIONS)

A migration is an SQL script; it runs once, inside a transaction, and its number
(position in the list, starting at 1) is recorded in ``schema_migrations``.
Never edit or reorder a released migration: append a new one.

Connections are per thread (FastAPI runs sync endpoints in a thread pool) and use
WAL mode with a busy timeout, so several worker processes can share the file.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

__all__ = ["Database", "DatabaseError"]

BUSY_TIMEOUT_MS = 5000
MEMORY = ":memory:"


class DatabaseError(Exception):
    """The database cannot be opened or migrated."""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._memory: sqlite3.Connection | None = None
        if self.path == MEMORY:
            # one shared connection: each new in-memory connection would be a new database
            self._memory = self._open()
        else:
            self._prepare_file(Path(self.path))

    # -- connections ---------------------------------------------------------------------------
    @staticmethod
    def _prepare_file(path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                # second-factor secrets live here: readable by the server user only
                fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
                os.close(fd)
        except OSError as exc:
            raise DatabaseError(f"cannot create the database {path}: {exc}") from exc

    def _open(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(
                self.path,
                timeout=BUSY_TIMEOUT_MS / 1000,
                isolation_level=None,  # explicit BEGIN/COMMIT in transaction()
                check_same_thread=self.path != MEMORY,
            )
        except sqlite3.Error as exc:
            raise DatabaseError(f"cannot open the database {self.path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path != MEMORY:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager  # pyright: ignore[reportDeprecated]
    def connection(self) -> Iterator[sqlite3.Connection]:
        """The connection of the current thread (serialised for an in-memory database)."""
        if self._memory is not None:
            with self._lock:
                yield self._memory
            return
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
        yield conn

    @contextmanager  # pyright: ignore[reportDeprecated]
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` … ``COMMIT``, rolled back on error."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # -- migrations ----------------------------------------------------------------------------
    def migrate(self, component: str, migrations: Sequence[str]) -> int:
        """Apply the migrations of ``component`` not applied yet; return its schema version."""
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " component TEXT NOT NULL,"
                " version INTEGER NOT NULL,"
                " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                " PRIMARY KEY (component, version))"
            )
            row = conn.execute(
                "SELECT MAX(version) FROM schema_migrations WHERE component = ?", (component,)
            ).fetchone()
            current = int(row[0] or 0)
            if current > len(migrations):
                raise DatabaseError(
                    f"database schema of {component!r} is at version {current}, newer than "
                    f"this server ({len(migrations)}): refusing to run an older release"
                )
            for version, script in enumerate(migrations[current:], start=current + 1):
                for statement in _statements(script):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (component, version) VALUES (?, ?)",
                    (component, version),
                )
            return len(migrations)

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _statements(script: str) -> list[str]:
    """Split a migration script into statements (``executescript`` would commit early)."""
    out: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                out.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise DatabaseError(f"incomplete SQL statement in migration: {buffer.strip()[:80]}")
    return out
