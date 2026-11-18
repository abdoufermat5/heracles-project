"""The logical dump of the application database, on both backends and across them.

PostgreSQL runs when ``HERACLES_TEST_POSTGRES_URL`` is set (see ``test_backends``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest

from heracles.auth.oidc import Pending, SqlPendingStore
from heracles.objects.activation import PluginOverrideStore
from heracles.storage import Database, DatabaseError
from heracles.storage.copy import component_migrations
from heracles.storage.dump import (
    NewerSchemaError,
    TargetNotEmptyError,
    dump_database,
    load_database,
)
from tests.storage.seed import check, seed
from tests.storage.test_backends import PG_URL

NewTarget = Callable[[str], str | Path]
BACKENDS = ["sqlite", "postgresql"]


@pytest.fixture
def new_target(tmp_path: Path) -> Iterator[NewTarget]:
    """``new_target(backend)``: the location of a new, empty database of that backend."""
    schemas: list[str] = []

    def make(backend: str) -> str | Path:
        if backend == "sqlite":
            return tmp_path / f"{uuid.uuid4().hex[:8]}.db"
        if not PG_URL:
            pytest.skip("HERACLES_TEST_POSTGRES_URL is not set")
        import psycopg

        schema = f"t_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(PG_URL, autocommit=True) as admin:
            admin.execute(cast("Any", f"CREATE SCHEMA {schema}"))
        schemas.append(schema)
        sep = "&" if "?" in PG_URL else "?"
        return f"{PG_URL}{sep}options={quote(f'-csearch_path={schema}')}"

    yield make
    if schemas and PG_URL:
        import psycopg

        with psycopg.connect(PG_URL, autocommit=True) as admin:
            for schema in schemas:
                admin.execute(cast("Any", f"DROP SCHEMA {schema} CASCADE"))


def versions(db: Database) -> dict[str, int]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT component, MAX(version) FROM schema_migrations GROUP BY component"
        ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


@pytest.mark.parametrize("target", BACKENDS)
@pytest.mark.parametrize("source", BACKENDS)
def test_round_trip_across_backends(
    source: str, target: str, new_target: NewTarget, tmp_path: Path
) -> None:
    src = Database(new_target(source))
    session_id = seed(src)
    dump = dump_database(src, tmp_path / "dump")
    src.close()
    assert "sessions" not in dump.tables and "second_factor_totp" in dump.tables
    assert dump.components["tasks"] == len(component_migrations()["tasks"])

    dst = Database(new_target(target))
    try:
        result = load_database(dst, tmp_path / "dump", dump.components, dump.tables)
        assert result.tables == dump.tables and result.upgraded == []
        check(dst, session_id)
        assert versions(dst)["tasks"] == dump.components["tasks"]
    finally:
        dst.close()


def test_dump_is_one_json_object_per_row_with_tagged_binary(
    new_target: NewTarget, tmp_path: Path
) -> None:
    db = Database(new_target("sqlite"))
    seed(db)
    dump_database(db, tmp_path / "d")
    lines = (tmp_path / "d" / "second_factor_webauthn.jsonl").read_text("utf-8").splitlines()
    (row,) = (json.loads(line) for line in lines)
    assert row["credential_id"] == {"$b64": "AP9rZXk="}
    assert row["sign_count"] == 3
    db.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_target_with_data_is_refused_unless_forced(
    backend: str, new_target: NewTarget, tmp_path: Path
) -> None:
    src = Database(new_target(backend))
    session_id = seed(src)
    dump = dump_database(src, tmp_path / "dump")
    src.close()

    dst = Database(new_target(backend))
    try:
        PluginOverrideStore(dst).set("sudo", True)
        PluginOverrideStore(dst).set("leftover", True)
        with pytest.raises(TargetNotEmptyError, match="plugin_overrides"):
            load_database(dst, tmp_path / "dump", dump.components, dump.tables)
        assert PluginOverrideStore(dst).load() == {"sudo": True, "leftover": True}  # untouched
        load_database(dst, tmp_path / "dump", dump.components, dump.tables, force=True)
        check(dst, session_id)  # the leftover is gone, the dump is in
    finally:
        dst.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_pending_oidc_logins_do_not_block_a_restore(
    backend: str, new_target: NewTarget, tmp_path: Path
) -> None:
    src = Database(new_target(backend))
    session_id = seed(src)
    dump = dump_database(src, tmp_path / "dump")
    src.close()

    dst = Database(new_target(backend))
    try:
        # a sign-in started on the target while it was being prepared
        SqlPendingStore(dst).add(Pending("s1", "n", "v", "main", "/", 1.0))
        load_database(dst, tmp_path / "dump", dump.components, dump.tables)
        check(dst, session_id)
    finally:
        dst.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_failing_load_leaves_the_target_untouched(
    backend: str, new_target: NewTarget, tmp_path: Path
) -> None:
    src = Database(new_target(backend))
    seed(src)
    dump = dump_database(src, tmp_path / "dump")
    src.close()
    # a row the schema refuses, after rows that load fine
    with (tmp_path / "dump" / "task_runs.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"id":99}\n')

    dst = Database(new_target(backend))
    try:
        with pytest.raises(DatabaseError):
            load_database(dst, tmp_path / "dump", dump.components, dump.tables)
        with dst.connection() as conn:
            for table in dump.tables:
                assert conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
    finally:
        dst.close()


def test_newer_schema_or_unknown_component_is_refused(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    tasks = len(component_migrations()["tasks"])
    with pytest.raises(NewerSchemaError, match="newer than this release"):
        load_database(db, tmp_path, {"tasks": tasks + 1}, {})
    with pytest.raises(NewerSchemaError, match="does not know"):
        load_database(db, tmp_path, {"from_the_future": 1}, {})
    db.close()


def test_unknown_table_and_hostile_names_are_refused(tmp_path: Path) -> None:
    db = Database(tmp_path / "h.db")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "nope.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    with pytest.raises(DatabaseError, match=r"do not know|does not know"):
        load_database(db, tmp_path / "x", {}, {"nope": 1})
    (tmp_path / "x" / "a b.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    with pytest.raises(DatabaseError):
        load_database(db, tmp_path / "x", {}, {'plugin_overrides"; DROP TABLE x; --': 1})
    db.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_an_older_archive_is_loaded_at_its_schema_then_upgraded(
    backend: str, new_target: NewTarget, tmp_path: Path
) -> None:
    """The archive predates the later ``tasks`` migrations (columns added to ``task_runs``)."""
    migrations = component_migrations()["tasks"]
    src = Database(new_target(backend))
    src.migrate("tasks", migrations[:1])
    with src.transaction() as conn:
        conn.execute(
            "INSERT INTO task_runs (directory, runner, kind, started_at, finished_at, status,"
            " counts, errors) VALUES ('main', 'access', '', 'a', 'b', 'ok', '{}', '[]')"
        )
    dump = dump_database(src, tmp_path / "dump")
    src.close()
    assert dump.components == {"tasks": 1}
    assert "reason" not in (tmp_path / "dump" / "task_runs.jsonl").read_text("utf-8")

    dst = Database(new_target(backend))
    try:
        result = load_database(dst, tmp_path / "dump", dump.components, dump.tables)
        assert result.upgraded == ["tasks"]
        assert versions(dst)["tasks"] == len(migrations)
        with dst.connection() as conn:
            row = conn.execute("SELECT runner, reason, reason_key FROM task_runs").fetchone()
        assert (row["runner"], row["reason"], row["reason_key"]) == ("access", None, None)
    finally:
        dst.close()


def test_every_component_with_migrations_is_in_the_registry() -> None:
    """A new component must be listed in ``component_migrations`` or backups would miss it."""
    import importlib
    import pkgutil

    import heracles
    import heracles_plugins

    registered = [id(m) for m in component_migrations().values()]
    found: list[str] = []
    for package in (heracles, heracles_plugins):
        for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            try:
                module = importlib.import_module(info.name)
            except ImportError:  # an optional dependency (dns, ...) is not installed
                continue
            for name in ("MIGRATIONS", "TASKS_MIGRATIONS"):
                migrations: object = getattr(module, name, None)
                if (
                    isinstance(migrations, tuple)
                    and migrations
                    and id(cast("tuple[object, ...]", migrations)) not in registered
                ):
                    found.append(f"{info.name}.{name}")
    assert not found, f"not in heracles.storage.copy.component_migrations: {found}"
