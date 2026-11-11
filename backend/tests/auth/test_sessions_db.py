"""SQLite-backed sessions: state shared by every process using the same database file."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from heracles.auth.sessions import SessionStore
from heracles.auth.sessions_db import SqliteSessionStore
from heracles.storage import Database

IDLE = 600.0
ABSOLUTE = 3600.0
DN = "uid=jdoe,ou=people,dc=example,dc=com"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Opaque:
    """Stands for a derived object (the ACL resolution) that cannot be stored as JSON."""

    label: str


@dataclass
class Pair:
    first: SqliteSessionStore
    second: SqliteSessionStore
    db: Database
    clock: Clock


@pytest.fixture
def pair(tmp_path: Path) -> Iterator[Pair]:
    """Two stores on separate connections of one file: two worker processes."""
    clock = Clock()
    path = tmp_path / "h.db"
    first_db = Database(path)
    second_db = Database(path)

    def store(db: Database) -> SqliteSessionStore:
        return SqliteSessionStore(db, idle_timeout=IDLE, absolute_timeout=ABSOLUTE, clock=clock)

    try:
        yield Pair(store(first_db), store(second_db), first_db, clock)
    finally:
        first_db.close()
        second_db.close()


def _rows(db: Database) -> int:
    with db.connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])


def test_satisfies_the_protocol(pair: Pair) -> None:
    store: SessionStore = pair.first
    assert store.get("missing") is None


def test_create_on_one_process_is_visible_on_the_other(pair: Pair) -> None:
    made = pair.first.create(DN, "main", second_factor_pending=True, second_factor_methods=["totp"])
    seen = pair.second.get(made.id)
    assert seen is not None
    assert (seen.user_dn, seen.directory_id) == (DN, "main")
    assert seen.second_factor_pending
    assert not seen.authenticated
    assert seen.second_factor_methods == ["totp"]
    assert seen.created_at == made.created_at


def test_the_session_id_is_not_stored_in_clear(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    with pair.db.connection() as conn:
        keys = [r[0] for r in conn.execute("SELECT id_hash FROM sessions")]
        dump = "\n".join(str(tuple(r)) for r in conn.execute("SELECT * FROM sessions"))
    assert len(keys) == 1
    assert keys[0] != made.id
    assert made.id not in dump


def test_changes_need_a_save_and_then_reach_the_other_process(pair: Pair) -> None:
    made = pair.first.create(DN, "main", second_factor_pending=True, second_factor_methods=["totp"])
    mine = pair.first.get(made.id)
    assert mine is not None
    mine.second_factor_failures += 1
    mine.cache["reauth_at"] = 1_000_123.5
    mine.cache["challenge"] = (b"\x00\xff\x10", 1_000_300.0)
    mine.cache["nested"] = {"a": [1, "two", None, True], "raw": b"x"}
    mine.cache["sso"] = "cas"

    unsaved = pair.second.get(made.id)
    assert unsaved is not None
    assert unsaved.second_factor_failures == 0
    assert unsaved.cache == {}

    pair.first.save(mine)
    seen = pair.second.get(made.id)
    assert seen is not None
    assert seen.second_factor_failures == 1
    assert seen.cache["reauth_at"] == 1_000_123.5
    assert isinstance(seen.cache["reauth_at"], float)
    assert seen.cache["challenge"] == (b"\x00\xff\x10", 1_000_300.0)
    assert isinstance(seen.cache["challenge"], tuple)
    assert isinstance(seen.cache["challenge"][0], bytes)
    assert seen.cache["nested"] == {"a": [1, "two", None, True], "raw": b"x"}
    assert seen.cache["sso"] == "cas"


def test_flags_and_methods_round_trip(pair: Pair) -> None:
    made = pair.first.create(DN, "main", second_factor_pending=True, second_factor_methods=["totp"])
    mine = pair.first.get(made.id)
    assert mine is not None
    mine.second_factor_pending = False
    mine.second_factor_methods.append("recovery")
    pair.first.save(mine)
    seen = pair.second.get(made.id)
    assert seen is not None
    assert seen.authenticated
    assert seen.second_factor_methods == ["totp", "recovery"]


def test_concurrent_saves_merge_instead_of_overwriting(pair: Pair) -> None:
    made = pair.first.create(DN, "main", second_factor_pending=True, second_factor_methods=["totp"])
    one = pair.first.get(made.id)
    two = pair.second.get(made.id)
    assert one is not None
    assert two is not None
    one.second_factor_failures += 1
    one.cache["a"] = 1
    two.second_factor_failures += 1
    two.cache["b"] = 2
    pair.first.save(one)
    pair.second.save(two)

    final = pair.first.get(made.id)
    assert final is not None
    assert final.second_factor_failures == 2  # counted, not overwritten
    assert final.cache == {"a": 1, "b": 2}


def test_a_failure_counter_reset_and_key_removal_are_saved(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    mine = pair.first.get(made.id)
    assert mine is not None
    mine.second_factor_failures = 3
    mine.cache["challenge"] = (b"c", 1.0)
    pair.first.save(mine)

    other = pair.second.get(made.id)
    assert other is not None
    other.second_factor_failures = 0
    del other.cache["challenge"]
    pair.second.save(other)

    again = pair.first.get(made.id)
    assert again is not None
    assert again.second_factor_failures == 0
    assert "challenge" not in again.cache


def test_saving_twice_in_a_row_is_harmless(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    mine = pair.first.get(made.id)
    assert mine is not None
    mine.second_factor_failures += 1
    pair.first.save(mine)
    pair.first.save(mine)
    seen = pair.second.get(made.id)
    assert seen is not None
    assert seen.second_factor_failures == 1


def test_rotate_retires_the_old_id_everywhere(pair: Pair) -> None:
    made = pair.first.create(DN, "main", second_factor_pending=True, second_factor_methods=["totp"])
    mine = pair.first.get(made.id)
    assert mine is not None
    mine.cache["sso"] = "cas"
    pair.first.save(mine)

    rotated = pair.first.rotate(made.id)
    assert rotated is not None
    assert rotated.id != made.id
    assert pair.second.get(made.id) is None
    assert pair.first.get(made.id) is None
    seen = pair.second.get(rotated.id)
    assert seen is not None
    assert seen.cache["sso"] == "cas"
    assert seen.created_at == made.created_at

    rotated.second_factor_pending = False
    pair.first.save(rotated)
    after = pair.second.get(rotated.id)
    assert after is not None
    assert after.authenticated
    assert _rows(pair.db) == 1


def test_rotate_of_an_unknown_session_is_none(pair: Pair) -> None:
    assert pair.first.rotate("nope") is None


def test_delete_removes_the_session_everywhere(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    assert pair.second.get(made.id) is not None
    gone = pair.first.delete(made.id)
    assert gone is not None
    assert gone.user_dn == DN
    assert pair.second.get(made.id) is None
    assert pair.first.delete(made.id) is None


def test_a_save_does_not_bring_back_a_deleted_or_rotated_session(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    stale = pair.second.get(made.id)
    assert stale is not None
    pair.first.delete(made.id)
    stale.cache["late"] = 1
    pair.second.save(stale)
    assert pair.first.get(made.id) is None
    assert _rows(pair.db) == 0

    other = pair.first.create(DN, "main")
    stale_other = pair.second.get(other.id)
    assert stale_other is not None
    rotated = pair.first.rotate(other.id)
    assert rotated is not None
    stale_other.cache["late"] = 1
    pair.second.save(stale_other)
    kept = pair.first.get(rotated.id)
    assert kept is not None
    assert "late" not in kept.cache


def test_idle_expiry_and_last_seen_refresh(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    pair.clock.now += IDLE  # exactly the limit is still alive
    refreshed = pair.second.get(made.id)
    assert refreshed is not None
    assert refreshed.last_seen == pair.clock.now
    pair.clock.now += IDLE - 1  # kept alive by the access above, on the other process
    assert pair.first.get(made.id) is not None
    pair.clock.now += IDLE + 1
    assert pair.second.get(made.id) is None
    assert pair.first.get(made.id) is None
    assert _rows(pair.db) == 0


def test_absolute_expiry_ignores_activity(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    step = IDLE / 2
    while pair.clock.now + step - made.created_at <= ABSOLUTE:
        pair.clock.now += step
        assert pair.second.get(made.id) is not None
    pair.clock.now += step  # idle-fresh, but past the absolute limit
    assert pair.first.get(made.id) is None


def test_rotate_of_an_expired_session_is_refused(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    pair.clock.now += IDLE + 1
    assert pair.second.rotate(made.id) is None
    assert pair.first.get(made.id) is None


def test_expired_rows_are_purged_when_a_session_is_created(pair: Pair) -> None:
    pair.first.create(DN, "main")
    pair.first.create(DN, "main")
    pair.clock.now += IDLE + 1
    assert _rows(pair.db) == 2
    pair.second.create(DN, "main")
    assert _rows(pair.db) == 1


def test_idle_timeout_can_change_at_runtime(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    pair.first.idle_timeout = 10
    pair.clock.now += 11
    assert pair.first.get(made.id) is None


def test_derived_objects_stay_in_the_process_and_never_break_saving(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    mine = pair.first.get(made.id)
    assert mine is not None
    acl = Opaque("secret-label")
    mine.cache["acl.resolved"] = acl
    mine.cache["reauth_at"] = 5.0
    pair.first.save(mine)  # must not raise

    # the same process gets the very same object back ...
    again = pair.first.get(made.id)
    assert again is not None
    assert again.cache["acl.resolved"] is acl
    # ... the other process sees only the storable part and recomputes the rest
    other = pair.second.get(made.id)
    assert other is not None
    assert other.cache == {"reauth_at": 5.0}
    # nothing of the object is in the database
    with pair.db.connection() as conn:
        stored = conn.execute("SELECT cache FROM sessions").fetchone()[0]
    assert "secret-label" not in stored


def test_each_process_keeps_its_own_derived_object(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    one = pair.first.get(made.id)
    two = pair.second.get(made.id)
    assert one is not None
    assert two is not None
    first_value = Opaque("v1")
    second_value = Opaque("v2")
    one.cache["acl.resolved"] = first_value
    pair.first.save(one)
    two.cache["acl.resolved"] = second_value
    pair.second.save(two)

    in_second = pair.second.get(made.id)
    assert in_second is not None
    assert in_second.cache["acl.resolved"] is second_value
    # the first process's value was superseded: it recomputes rather than use a stale one
    in_first = pair.first.get(made.id)
    assert in_first is not None
    assert "acl.resolved" not in in_first.cache


def test_invalidating_a_derived_object_reaches_the_other_process(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    one = pair.first.get(made.id)
    assert one is not None
    one.cache["acl.resolved"] = Opaque("v1")
    pair.first.save(one)
    holder = pair.first.get(made.id)
    assert holder is not None
    assert "acl.resolved" in holder.cache

    # ``invalidate_acl_cache`` pops the key; the save carries it to the shared row
    del holder.cache["acl.resolved"]
    pair.first.save(holder)
    for store in (pair.first, pair.second):
        seen = store.get(made.id)
        assert seen is not None
        assert "acl.resolved" not in seen.cache
    with pair.db.connection() as conn:
        assert conn.execute("SELECT cache FROM sessions").fetchone()[0] == "{}"


def test_unstorable_values_do_not_follow_a_rotation(pair: Pair) -> None:
    made = pair.first.create(DN, "main")
    mine = pair.first.get(made.id)
    assert mine is not None
    mine.cache["acl.resolved"] = Opaque("x")
    mine.cache["reauth_at"] = 1.0
    pair.first.save(mine)
    rotated = pair.first.rotate(made.id)
    assert rotated is not None
    assert rotated.cache == {"reauth_at": 1.0}


def test_sessions_survive_a_restart(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "h.db"
    db = Database(path)
    made = SqliteSessionStore(db, idle_timeout=IDLE, absolute_timeout=ABSOLUTE, clock=clock).create(
        DN, "main"
    )
    db.close()
    again_db = Database(path)
    try:
        again = SqliteSessionStore(
            again_db, idle_timeout=IDLE, absolute_timeout=ABSOLUTE, clock=clock
        )
        assert again.get(made.id) is not None
    finally:
        again_db.close()
