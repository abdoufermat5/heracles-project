"""The application SQLite database: connections, transactions, migrations."""

from __future__ import annotations

import stat
import threading
from pathlib import Path

import pytest

from heracles.storage import Database, DatabaseError

V1 = "CREATE TABLE things (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
V2 = """
ALTER TABLE things ADD COLUMN size INTEGER NOT NULL DEFAULT 0;
CREATE INDEX things_name ON things (name);
"""


def test_migrations_apply_once_per_component(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    assert db.migrate("demo", [V1]) == 1
    assert db.migrate("demo", [V1]) == 1  # idempotent
    assert db.migrate("demo", [V1, V2]) == 2
    assert db.migrate("other", [V1.replace("things", "others")]) == 1
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT component, version FROM schema_migrations ORDER BY component, version"
        ).fetchall()
        conn.execute("INSERT INTO things (name, size) VALUES ('a', 3)")
    assert [tuple(r) for r in rows] == [("demo", 1), ("demo", 2), ("other", 1)]


def test_failed_migration_is_rolled_back(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    with pytest.raises(Exception, match="nope"):
        db.migrate("demo", [V1 + "\nINSERT INTO nope VALUES (1);"])
    with db.connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "things" not in tables
    assert db.migrate("demo", [V1]) == 1


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    db.migrate("demo", [V1, V2])
    with pytest.raises(DatabaseError, match="newer than this server"):
        Database(tmp_path / "h.db").migrate("demo", [V1])


def test_incomplete_statement_is_refused() -> None:
    with pytest.raises(DatabaseError, match="incomplete"):
        Database(":memory:").migrate("demo", ["CREATE TABLE x (id INTEGER"])


def test_file_is_private_and_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "h.db"
    db = Database(path)
    db.migrate("demo", [V1])
    with db.transaction() as conn:
        conn.execute("INSERT INTO things (name) VALUES ('kept')")
    db.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = Database(path)
    with again.connection() as conn:
        assert conn.execute("SELECT name FROM things").fetchone()[0] == "kept"


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    db.migrate("demo", [V1])
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO things (name) VALUES ('lost')")
        raise RuntimeError
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM things").fetchone()[0] == 0


def test_concurrent_writers_from_threads(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    db.migrate("demo", [V1])

    def work(n: int) -> None:
        for i in range(25):
            with db.transaction() as conn:
                conn.execute("INSERT INTO things (name) VALUES (?)", (f"{n}-{i}",))

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM things").fetchone()[0] == 200


def test_unwritable_location_is_reported(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(DatabaseError, match="cannot create"):
        Database(blocker / "h.db")
