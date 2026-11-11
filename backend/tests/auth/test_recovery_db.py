"""SQLite-backed recovery token store."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from heracles.auth.recovery import TokenRecord, TokenStore, hash_token
from heracles.auth.recovery_db import SqliteTokenStore
from heracles.storage import Database

DN = "uid=jdoe,ou=people,dc=example,dc=com"
SAME_DN = "UID=jdoe, ou=People,dc=example,dc=com"
MAX_AGE = 600.0


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "h.db")
    yield database
    database.close()


@pytest.fixture
def store(db: Database, clock: Clock) -> TokenStore:
    return SqliteTokenStore(db, clock)


def _record(token: str, clock: Clock, kind: str = "recovery") -> TokenRecord:
    return TokenRecord(user_dn=DN, token_hash=hash_token(token), created_at=clock(), kind=kind)


def test_consume_once(store: TokenStore, clock: Clock) -> None:
    store.put(_record("t1", clock))
    assert store.consume(DN, hash_token("t1"), kind="recovery", max_age=MAX_AGE) is True
    assert store.consume(DN, hash_token("t1"), kind="recovery", max_age=MAX_AGE) is False


def test_put_replaces_previous_token(store: TokenStore, clock: Clock) -> None:
    store.put(_record("old", clock))
    store.put(_record("new", clock))
    assert store.consume(DN, hash_token("old"), kind="recovery", max_age=MAX_AGE) is False
    assert store.consume(DN, hash_token("new"), kind="recovery", max_age=MAX_AGE) is True


def test_wrong_token_does_not_burn_the_valid_one(store: TokenStore, clock: Clock) -> None:
    store.put(_record("good", clock))
    assert store.consume(DN, hash_token("guess"), kind="recovery", max_age=MAX_AGE) is False
    assert store.consume(DN, hash_token("good"), kind="recovery", max_age=MAX_AGE) is True


def test_expired_token_is_refused_and_dropped(store: TokenStore, clock: Clock) -> None:
    store.put(_record("t", clock))
    clock.now += MAX_AGE + 1
    assert store.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is False
    clock.now -= MAX_AGE + 1  # even back in time it is gone
    assert store.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is False


def test_token_at_the_age_limit_is_valid(store: TokenStore, clock: Clock) -> None:
    store.put(_record("t", clock))
    clock.now += MAX_AGE
    assert store.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is True


def test_kinds_are_separate(store: TokenStore, clock: Clock) -> None:
    store.put(_record("t", clock, kind="invite"))
    assert store.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is False
    store.put(_record("r", clock, kind="recovery"))  # does not replace the invite
    assert store.consume(DN, hash_token("t"), kind="invite", max_age=MAX_AGE) is True
    assert store.consume(DN, hash_token("r"), kind="recovery", max_age=MAX_AGE) is True


def test_dn_is_case_and_spacing_insensitive(store: TokenStore, clock: Clock) -> None:
    store.put(_record("t", clock))
    assert store.consume(SAME_DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is True


def test_other_user_cannot_consume(store: TokenStore, clock: Clock) -> None:
    store.put(_record("t", clock))
    other = "uid=other,ou=people,dc=example,dc=com"
    assert store.consume(other, hash_token("t"), kind="recovery", max_age=MAX_AGE) is False
    assert store.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is True


def test_token_is_shared_between_instances(tmp_path: Path, clock: Clock) -> None:
    first_db = Database(tmp_path / "h.db")
    second_db = Database(tmp_path / "h.db")
    try:
        first = SqliteTokenStore(first_db, clock)
        second = SqliteTokenStore(second_db, clock)
        first.put(_record("t", clock))
        assert second.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is True
        assert first.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE) is False
    finally:
        first_db.close()
        second_db.close()


def test_concurrent_consume_succeeds_exactly_once(tmp_path: Path, clock: Clock) -> None:
    path = tmp_path / "h.db"
    seed_db = Database(path)
    SqliteTokenStore(seed_db, clock).put(_record("t", clock))
    seed_db.close()

    workers = 8
    # Each worker is its own "process": own Database (own connections) on the same file.
    barrier = threading.Barrier(workers)
    results: list[bool] = []
    lock = threading.Lock()

    def run() -> None:
        database = Database(path)
        try:
            s = SqliteTokenStore(database, clock)
            barrier.wait()
            ok = s.consume(DN, hash_token("t"), kind="recovery", max_age=MAX_AGE)
            with lock:
                results.append(ok)
        finally:
            database.close()  # connections are per thread: close in the thread that opened it

    threads = [threading.Thread(target=run) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == workers
    assert results.count(True) == 1
