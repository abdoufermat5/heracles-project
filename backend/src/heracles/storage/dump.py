"""Portable logical dump of the application database (``heracles backup`` / ``restore``).

One JSON-lines file per table, the same on SQLite and PostgreSQL, so an archive taken on one
backend restores on the other. A line is one row, an object mapping column name to value: JSON
strings, numbers and ``null`` as they are, binary values as ``{"$b64": "<base64>"}``. Rows are
written in primary-key order.

* :func:`dump_database` reads every table inside one transaction (writers are serialised by
  :meth:`Database.transaction`, so the files are one consistent snapshot).
* :func:`load_database` creates the schema of every component at the version of the archive (the
  data was written with those columns), loads all tables in one transaction, then applies the
  migrations the archive predates.

Tables holding only short-lived state (sessions, login failures, recovery links, the task lease,
caches) are left out: restoring them would only revive stale sessions.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from heracles.storage.copy import component_migrations
from heracles.storage.database import Database, DatabaseError

__all__ = [
    "EPHEMERAL_TABLES",
    "SECRET_COLUMNS",
    "SECRET_TABLES",
    "DatabaseDump",
    "LoadResult",
    "NewerSchemaError",
    "TargetNotEmptyError",
    "check_versions",
    "dump_database",
    "load_database",
    "table_file",
]

#: Short-lived state, neither dumped nor required to be empty when restoring.
EPHEMERAL_TABLES = frozenset(
    {
        "sessions",
        "ratelimit_failures",
        "recovery_tokens",
        "task_lease",
        "listing_epochs",
        "posix_id_reservations",
        "public_forms_nonces",
        "public_forms_events",
        "oidc_pending",
    }
)

#: Secret columns written as ``null`` when a dump excludes secrets (a TOTP seed cannot be hashed:
#: the server needs it in clear to check a code, so it is never exported on request).
SECRET_COLUMNS: Mapping[str, frozenset[str]] = {"second_factor_totp": frozenset({"secret"})}

#: Tables written empty when a dump excludes secrets (digests of the recovery codes).
SECRET_TABLES = frozenset({"second_factor_recovery"})

SCHEMA_TABLE = "schema_migrations"
BINARY_KEY = "$b64"
BATCH = 500
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class NewerSchemaError(DatabaseError):
    """The archive was written by a newer release than this one."""


class TargetNotEmptyError(DatabaseError):
    """The target database already holds data (restore needs ``--force``)."""


@dataclass(slots=True)
class DatabaseDump:
    """What :func:`dump_database` wrote."""

    dialect: str
    #: Schema version (number of migrations applied) of each component.
    components: dict[str, int] = field(default_factory=lambda: {})
    #: Rows written per table.
    tables: dict[str, int] = field(default_factory=lambda: {})


@dataclass(slots=True)
class LoadResult:
    """What :func:`load_database` did."""

    tables: dict[str, int] = field(default_factory=lambda: {})
    #: Components whose schema was older than this release's and was upgraded after the load.
    upgraded: list[str] = field(default_factory=lambda: [])


def table_file(table: str) -> str:
    """Archive path of the file holding ``table``."""
    return f"database/{table}.jsonl"


def _quote(identifier: str) -> str:
    if not _IDENTIFIER.match(identifier):
        raise DatabaseError(f"invalid identifier in the archive: {identifier!r}")
    return f'"{identifier}"'


def _table_names(db: Database, conn: Any) -> list[str]:
    if db.dialect == "postgresql":
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            " ORDER BY table_name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name"
        ).fetchall()
    return [str(r[0]) for r in rows]


def _versions(db: Database, conn: Any) -> dict[str, int]:
    if SCHEMA_TABLE not in _table_names(db, conn):
        return {}
    rows = conn.execute(
        "SELECT component, MAX(version) FROM schema_migrations GROUP BY component"
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _encode(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {BINARY_KEY: base64.b64encode(bytes(cast("bytes", value))).decode("ascii")}
    if value is None or isinstance(value, (str, int, float)):
        return value
    raise DatabaseError(f"cannot dump a value of type {type(value).__name__}")


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        encoded = value.get(BINARY_KEY)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if len(value) != 1 or not isinstance(encoded, str):  # pyright: ignore[reportUnknownArgumentType]
            raise DatabaseError("malformed value in the archive")
        return base64.b64decode(encoded, validate=True)
    return value


def dump_database(db: Database, dest: Path, *, exclude_secrets: bool = False) -> DatabaseDump:
    """Write one ``<table>.jsonl`` per persistent table into the directory ``dest``.

    ``exclude_secrets``: second-factor seeds and recovery code digests are left out (the
    users enrol again after a restore).
    """
    dest.mkdir(parents=True, exist_ok=True)
    with db.transaction() as conn:
        result = DatabaseDump(db.dialect, _versions(db, conn))
        for table in _table_names(db, conn):
            if table == SCHEMA_TABLE or table in EPHEMERAL_TABLES:
                continue
            count = 0
            with (dest / f"{table}.jsonl").open("w", encoding="utf-8", newline="\n") as out:
                if exclude_secrets and table in SECRET_TABLES:
                    result.tables[table] = 0
                    continue
                blanked = SECRET_COLUMNS.get(table, frozenset()) if exclude_secrets else frozenset()
                for row in conn.execute(f"SELECT * FROM {_quote(table)} ORDER BY 1"):  # noqa: S608
                    names = row.keys()
                    record = {
                        name: None if name in blanked else _encode(row[i])
                        for i, name in enumerate(names)
                    }
                    out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    out.write("\n")
                    count += 1
            result.tables[table] = count
    return result


def check_versions(components: Mapping[str, int]) -> None:
    """Refuse an archive newer than this release (or naming a component it does not know)."""
    known = component_migrations()
    for component, version in components.items():
        migrations = known.get(component)
        if migrations is None:
            raise NewerSchemaError(
                f"the archive holds the component {component!r}, which this release does not know"
            )
        if version > len(migrations):
            raise NewerSchemaError(
                f"the archive has {component!r} at schema version {version}: newer than this "
                f"release ({len(migrations)}); upgrade Heracles before restoring"
            )


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as src:
        for number, line in enumerate(src, start=1):
            if not line.strip():
                continue
            try:
                record: object = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatabaseError(f"{path.name} line {number}: {exc}") from exc
            if not isinstance(record, dict):
                raise DatabaseError(f"{path.name} line {number}: a row must be an object")
            yield {str(k): _decode(v) for k, v in record.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def _insert(conn: Any, table: str, path: Path) -> tuple[int, list[str]]:
    count = 0
    columns: list[str] | None = None
    batch: list[tuple[Any, ...]] = []
    sql = ""
    for row in _rows(path):
        if columns is None:
            columns = list(row)
            sql = (
                f"INSERT INTO {_quote(table)} ({', '.join(_quote(c) for c in columns)})"  # noqa: S608
                f" VALUES ({', '.join('?' * len(columns))})"
            )
        if set(row) != set(columns):
            raise DatabaseError(f"{path.name}: the rows do not all have the same columns")
        batch.append(tuple(row[c] for c in columns))
        count += 1
        if len(batch) >= BATCH:
            conn.executemany(sql, batch)
            batch = []
    if batch:
        conn.executemany(sql, batch)
    return count, columns or []


def _advance_sequence(conn: Any, table: str) -> None:
    """Keep a PostgreSQL serial column ahead of the ids just inserted."""
    sequence = conn.execute("SELECT pg_get_serial_sequence(?, 'id')", (_quote(table),)).fetchone()
    if sequence is not None and sequence[0]:
        conn.execute(
            "SELECT setval(?, (SELECT MAX(id) FROM " + _quote(table) + "))",  # noqa: S608
            (sequence[0],),
        )


def load_database(
    db: Database,
    source: Path,
    components: Mapping[str, int],
    tables: Mapping[str, int],
    *,
    force: bool = False,
) -> LoadResult:
    """Load the dump in ``source`` (a directory of ``<table>.jsonl`` files) into ``db``.

    ``components`` and ``tables`` come from the archive manifest. A target holding data is
    refused unless ``force`` (its rows are then replaced). All rows are loaded in one transaction.
    """
    check_versions(components)
    registry = component_migrations()
    with db.connection() as conn:
        current = _versions(db, conn)
        existing = [t for t in _table_names(db, conn) if t != SCHEMA_TABLE]
        if not force:
            filled = [
                t
                for t in existing
                if t not in EPHEMERAL_TABLES
                and conn.execute(f"SELECT 1 FROM {_quote(t)} LIMIT 1").fetchone() is not None  # noqa: S608
            ]
            if filled:
                raise TargetNotEmptyError(
                    "the target database is not empty (" + ", ".join(sorted(filled)) + "); "
                    "use --force to replace its content"
                )
    # The data has the columns of the version it was written with: build that schema first.
    for component, migrations in registry.items():
        upto = max(components.get(component, 0), current.get(component, 0))
        if upto:
            db.migrate(component, migrations[:upto])
    result = LoadResult()
    with db.transaction() as conn:
        live = [t for t in _table_names(db, conn) if t != SCHEMA_TABLE]
        unknown = sorted(t for t in tables if t not in live or t in EPHEMERAL_TABLES)
        if unknown:
            raise DatabaseError(
                "the archive holds tables this release does not know: " + ", ".join(unknown)
            )
        for table in live:
            conn.execute(f"DELETE FROM {_quote(table)}")  # noqa: S608
        for table in tables:
            count, columns = _insert(conn, table, source / f"{table}.jsonl")
            result.tables[table] = count
            if db.dialect == "postgresql" and count and "id" in columns:
                _advance_sequence(conn, table)
    for component, migrations in registry.items():
        if components.get(component, len(migrations)) < len(migrations):
            result.upgraded.append(component)
        db.migrate(component, migrations)
    return result
