# ruff: noqa: S608  (table names come from the source file's own catalogue, never from input)
"""Copy an application SQLite database into PostgreSQL (``heracles db migrate-to-postgres``).

Lets a single node scale out to several replicas: the schema of every component is created
on the PostgreSQL side with the normal migrations, then each table is copied row by row.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from heracles.storage.database import Database, DatabaseError, Migration

__all__ = ["component_migrations", "copy_sqlite_to_postgres"]


def component_migrations() -> dict[str, Sequence[str | Migration]]:
    """Every component that keeps tables in the application database."""
    from heracles.auth import ratelimit_db, recovery_db, second_factor_db, sessions_db
    from heracles.objects import activation, listing_epochs
    from heracles.tasks import scheduler

    return {
        sessions_db.COMPONENT: sessions_db.MIGRATIONS,
        ratelimit_db.COMPONENT: ratelimit_db.MIGRATIONS,
        recovery_db.COMPONENT: recovery_db.MIGRATIONS,
        second_factor_db.COMPONENT: second_factor_db.MIGRATIONS,
        "tasks": scheduler.TASKS_MIGRATIONS,
        activation.COMPONENT: activation.MIGRATIONS,
        listing_epochs.COMPONENT: listing_epochs.MIGRATIONS,
    }


def copy_sqlite_to_postgres(source: Path, url: str) -> dict[str, int]:
    """Copy the data of the SQLite file ``source`` into the PostgreSQL database ``url``.

    Returns the number of rows copied per table. The destination tables must be empty.
    """
    if not source.is_file():
        raise DatabaseError(f"no such database file: {source}")
    dest = Database(url)
    if dest.dialect != "postgresql":
        raise DatabaseError("the destination must be a postgresql:// URL")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        migrations = component_migrations()
        versions = src.execute(
            "SELECT component, MAX(version) FROM schema_migrations GROUP BY component"
        ).fetchall()
        for component, version in versions:
            known = migrations.get(component)
            if known is None or version > len(known):
                raise DatabaseError(
                    f"the source has {component!r} at version {version}: newer than this server"
                )
        for component, ms in migrations.items():
            dest.migrate(component, ms)
        tables = [
            r[0]
            for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                " AND name <> 'schema_migrations' ORDER BY name"
            )
        ]
        copied: dict[str, int] = {}
        with dest.transaction() as conn:
            for table in tables:
                if conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                    raise DatabaseError(f"destination table {table!r} is not empty")
                cursor = src.execute(f"SELECT * FROM {table}")
                columns = [c[0] for c in cursor.description]
                rows = cursor.fetchall()
                if rows:
                    conn.executemany(
                        f"INSERT INTO {table} ({', '.join(columns)})"
                        f" VALUES ({', '.join('?' * len(columns))})",
                        rows,
                    )
                if "id" in columns and rows:
                    # keep the serial column ahead of the copied ids
                    conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
                        f" (SELECT MAX(id) FROM {table}))"
                    )
                copied[table] = len(rows)
        return copied
    finally:
        src.close()
        dest.close()
