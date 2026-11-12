"""The application's own database: SQLite (single node) or PostgreSQL (several hosts).

Heracles keeps the directory as the source of truth for objects; this database
holds the server-side state that has no place in the directory (second-factor
registrations first, more later). Every feature owns a *component* with its own
ordered list of migrations::

    db = Database(Path("/var/lib/heracles/heracles.db"))
    db.migrate("second_factor", SECOND_FACTOR_MIGRATIONS)

A migration is an SQL script; it runs once, inside a transaction, and its number
(position in the list, starting at 1) is recorded in ``schema_migrations``.
Never edit or reorder a released migration: append a new one.

``Database(target)`` picks the backend: a ``postgresql://`` URL gives a
:class:`~heracles.storage.postgres.PostgresDatabase`, anything else is a SQLite file (or
``":memory:"``). Component code is written once, in portable SQL:

* placeholders are ``?`` (the PostgreSQL backend rewrites them to ``%s``);
* upserts use ``INSERT ... ON CONFLICT (...) DO UPDATE`` (``INSERT OR IGNORE`` is accepted and
  rewritten for PostgreSQL); no ``rowid``, no ``lastrowid``;
* rows are indexable by position and by column name;
* DDL in a migration may use ``INTEGER PRIMARY KEY AUTOINCREMENT``, ``BLOB`` and ``REAL``: a plain
  string migration is translated for PostgreSQL (``BIGSERIAL``, ``BYTEA``, ``DOUBLE PRECISION``).
  A migration whose PostgreSQL form needs more than that is a :class:`Migration` giving both
  scripts; the SQLite script of a released migration is never edited.
* ``transaction()`` serialises writers: ``BEGIN IMMEDIATE`` on SQLite, a transaction-level
  advisory lock on PostgreSQL (so read-then-write blocks, such as the task lease, behave the same
  on both, without retry loops).

SQLite connections are per thread (FastAPI runs sync endpoints in a thread pool) and use
WAL mode with a busy timeout, so several worker processes on one host can share the file.
PostgreSQL connections come from a pool that checks them before handing them out.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["Database", "DatabaseError", "Migration", "SqliteDatabase", "is_postgres_url"]

BUSY_TIMEOUT_MS = 5000
MEMORY = ":memory:"


class DatabaseError(Exception):
    """The database cannot be opened or migrated."""


@dataclass(frozen=True, slots=True)
class Migration:
    """A migration with one script per dialect (when the automatic translation is not enough)."""

    sqlite: str
    postgresql: str


def is_postgres_url(target: object) -> bool:
    return isinstance(target, str) and target.startswith(("postgresql://", "postgres://"))


_DDL_TRANSLATIONS = (
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.I), "BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\bBLOB\b", re.I), "BYTEA"),
    # REAL is a 4-byte float on PostgreSQL: epoch seconds need the 8-byte one
    (re.compile(r"\bREAL\b", re.I), "DOUBLE PRECISION"),
)
_INSERT_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", re.I)


@lru_cache(maxsize=512)
def to_postgres(sql: str) -> str:
    """The PostgreSQL form of a statement written in the portable subset (see the module doc)."""
    for pattern, replacement in _DDL_TRANSLATIONS:
        sql = pattern.sub(replacement, sql)
    if _INSERT_OR_IGNORE.match(sql):
        sql = _INSERT_OR_IGNORE.sub("INSERT INTO", sql, count=1).rstrip().rstrip(";")
        sql += " ON CONFLICT DO NOTHING"
    return sql.replace("%", "%%").replace("?", "%s")


class Database:
    """Base of the two backends; ``Database(target)`` returns the right one."""

    dialect = ""

    def __new__(cls, target: Path | str) -> Database:
        if cls is Database:
            if is_postgres_url(target):
                from heracles.storage.postgres import PostgresDatabase

                return object.__new__(PostgresDatabase)
            return object.__new__(SqliteDatabase)
        return object.__new__(cls)

    def connection(self) -> Any:  # a context manager yielding a connection
        raise NotImplementedError

    def transaction(self) -> Any:  # a context manager yielding a connection
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def _script(self, migration: str | Migration) -> str:
        if isinstance(migration, Migration):
            return migration.postgresql if self.dialect == "postgresql" else migration.sqlite
        return to_postgres(migration) if self.dialect == "postgresql" else migration

    def migrate(self, component: str, migrations: Sequence[str | Migration]) -> int:
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
            for version, migration in enumerate(migrations[current:], start=current + 1):
                for statement in statements(self._script(migration)):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (component, version) VALUES (?, ?)",
                    (component, version),
                )
            return len(migrations)


class SqliteDatabase(Database):
    dialect = "sqlite"

    def __init__(self, path: Path | str) -> None:  # pyright: ignore[reportInconsistentConstructor]
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

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def statements(script: str) -> list[str]:
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
