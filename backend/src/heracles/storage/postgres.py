"""The PostgreSQL backend of the application database (optional extra ``postgres``).

Several Heracles replicas on different hosts share one PostgreSQL database; see
:mod:`heracles.storage.database` for the portable SQL subset component code sticks to.

* Connections come from a ``psycopg_pool`` pool in autocommit mode; each one is checked before
  it is handed out, so a connection dropped by the server or a restart is replaced
  transparently.
* ``transaction()`` is ``BEGIN`` plus a transaction-level advisory lock. That gives the same
  guarantee as SQLite's ``BEGIN IMMEDIATE`` (one writer at a time, read-then-write blocks cannot
  interleave), so component code needs no serialization-failure retry loops. Write
  transactions here are a few single-row statements, so the cost of one cluster-wide writer
  at a time is small next to the LDAP round trips of the request.
* ``connection()`` outside a transaction runs each statement in its own implicit transaction.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from heracles.storage.database import Database, DatabaseError, to_postgres

__all__ = ["PostgresDatabase"]

#: Arbitrary constant identifying Heracles' writer lock among the server's advisory locks.
WRITER_LOCK_KEY = 0x48524301
POOL_MAX = 10
POOL_TIMEOUT = 10.0


class Row(tuple[Any, ...]):
    """A result row readable by position and by column name (like ``sqlite3.Row``)."""

    _names: tuple[str, ...]

    def __new__(cls, values: Sequence[Any], names: tuple[str, ...]) -> Row:
        row = super().__new__(cls, values)
        row._names = names
        return row

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            try:
                return super().__getitem__(self._names.index(key))
            except ValueError:
                raise IndexError(f"no such column: {key}") from None
        return super().__getitem__(key)

    def keys(self) -> list[str]:
        return list(self._names)


def _row_factory(cursor: Any) -> Callable[[Sequence[Any]], Row]:
    names = tuple(c.name for c in cursor.description or ())

    def make(values: Sequence[Any]) -> Row:
        return Row(values, names)

    return make


class Connection:
    """The subset of the ``sqlite3.Connection`` API component code uses, on a psycopg one."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.execute(to_postgres(sql), tuple(params))
        return cur

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> Any:
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.executemany(to_postgres(sql), [tuple(r) for r in rows])
        return cur


class PostgresDatabase(Database):
    dialect = "postgresql"

    def __init__(self, url: Path | str) -> None:  # pyright: ignore[reportInconsistentConstructor]
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise DatabaseError(
                "a postgresql:// database needs the 'postgres' extra (heracles[postgres])"
            ) from exc
        self.url = str(url)
        self._local = threading.local()
        try:
            self._pool = ConnectionPool(
                self.url,
                min_size=1,
                max_size=POOL_MAX,
                timeout=POOL_TIMEOUT,
                kwargs={"autocommit": True},
                check=ConnectionPool.check_connection,
                open=False,
            )
            self._pool.open(wait=True, timeout=POOL_TIMEOUT)
        except Exception as exc:
            raise DatabaseError(f"cannot open the PostgreSQL database: {exc}") from exc

    @contextmanager  # pyright: ignore[reportDeprecated]
    def connection(self) -> Iterator[Connection]:
        """The connection of the current thread (borrowed from the pool for the block)."""
        held: Connection | None = getattr(self._local, "conn", None)
        if held is not None:  # nested use inside a block of this thread
            yield held
            return
        with self._pool.connection() as raw:
            held = Connection(raw)
            self._local.conn = held
            try:
                yield held
            finally:
                self._local.conn = None

    @contextmanager  # pyright: ignore[reportDeprecated]
    def transaction(self) -> Iterator[Connection]:
        """``BEGIN`` + advisory writer lock … ``COMMIT``, rolled back on error."""
        with self.connection() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(f"SELECT pg_advisory_xact_lock({WRITER_LOCK_KEY})")
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def close(self) -> None:
        self._pool.close()
