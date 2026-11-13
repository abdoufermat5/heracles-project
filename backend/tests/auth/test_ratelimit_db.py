"""SQLite-backed login rate limiter: same policy as the in-memory one, shared state."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from heracles.auth.ratelimit import LoginLimiter, RateLimiter
from heracles.auth.ratelimit_db import SqliteRateLimiter
from heracles.storage import Database


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "h.db")
    yield database
    database.close()


def test_satisfies_the_protocol(db: Database) -> None:
    limiter: LoginLimiter = SqliteRateLimiter(db)
    assert limiter.key("10.0.0.1", " JDoe ") == RateLimiter.key("10.0.0.1", "jdoe")


def test_delays_match_the_in_memory_limiter(db: Database) -> None:
    clock = Clock()
    memory = RateLimiter(clock=clock)
    shared = SqliteRateLimiter(db, clock=clock)
    key = "10.0.0.1|jdoe"
    for step in range(14):
        assert shared.retry_after(key) == pytest.approx(memory.retry_after(key)), step
        memory.record_failure(key)
        shared.record_failure(key)
        assert shared.retry_after(key) == pytest.approx(memory.retry_after(key)), step
        clock.now += 1.0
    assert shared.retry_after(key) > 0  # the cap (900 s) is reached, still blocked


def test_free_attempts_then_doubling(db: Database) -> None:
    clock = Clock()
    limiter = SqliteRateLimiter(db, free_attempts=2, base_delay=2.0, max_delay=10.0, clock=clock)
    key = "k"
    limiter.record_failure(key)
    assert limiter.retry_after(key) == 0.0  # first of the two free attempts
    limiter.record_failure(key)
    assert limiter.retry_after(key) == pytest.approx(2.0)  # free attempts used up
    clock.now += 2.0
    limiter.record_failure(key)
    assert limiter.retry_after(key) == pytest.approx(4.0)
    clock.now += 4.0
    limiter.record_failure(key)
    assert limiter.retry_after(key) == pytest.approx(8.0)
    clock.now += 8.0
    limiter.record_failure(key)
    assert limiter.retry_after(key) == pytest.approx(10.0)  # capped


def test_state_is_shared_between_instances(tmp_path: Path) -> None:
    clock = Clock()
    first_db = Database(tmp_path / "h.db")
    second_db = Database(tmp_path / "h.db")
    try:
        first = SqliteRateLimiter(first_db, clock=clock)
        second = SqliteRateLimiter(second_db, clock=clock)
        key = first.key("10.0.0.1", "jdoe")
        for _ in range(5):
            assert first.retry_after(key) == 0.0
            first.record_failure(key)
        assert second.retry_after(key) > 0
        second.record_success(key)
        assert first.retry_after(key) == 0.0
    finally:
        first_db.close()
        second_db.close()


def test_failures_from_two_instances_add_up(tmp_path: Path) -> None:
    clock = Clock()
    first_db = Database(tmp_path / "h.db")
    second_db = Database(tmp_path / "h.db")
    try:
        first = SqliteRateLimiter(first_db, free_attempts=4, clock=clock)
        second = SqliteRateLimiter(second_db, free_attempts=4, clock=clock)
        for _ in range(2):
            first.record_failure("k")
            second.record_failure("k")
        assert first.retry_after("k") > 0
    finally:
        first_db.close()
        second_db.close()


def test_success_resets(db: Database) -> None:
    clock = Clock()
    limiter = SqliteRateLimiter(db, clock=clock)
    for _ in range(6):
        limiter.record_failure("k")
    assert limiter.retry_after("k") > 0
    limiter.record_success("k")
    assert limiter.retry_after("k") == 0.0
    limiter.record_failure("k")  # counting restarts from zero
    assert limiter.retry_after("k") == 0.0


def test_forget_after_resets(db: Database) -> None:
    clock = Clock()
    limiter = SqliteRateLimiter(db, forget_after=100.0, clock=clock)
    for _ in range(6):
        limiter.record_failure("k")
    clock.now += 101.0
    assert limiter.retry_after("k") == 0.0
    limiter.record_failure("k")  # a forgotten key restarts from one failure
    assert limiter.retry_after("k") == 0.0


def test_stale_rows_are_purged_and_table_is_bounded(db: Database) -> None:
    clock = Clock()
    limiter = SqliteRateLimiter(db, forget_after=100.0, max_entries=20, clock=clock)
    for i in range(10):
        limiter.record_failure(f"old{i}")
    clock.now += 101.0
    limiter.record_failure("fresh")
    assert _count(db) == 1  # the stale rows went away on the write path

    for i in range(200):
        clock.now += 0.001
        limiter.record_failure(f"flood{i}")
    assert _count(db) <= 20
    assert limiter.retry_after("flood199") == 0.0  # newest entries survive eviction


def test_hostile_keys_are_inert(db: Database) -> None:
    limiter = SqliteRateLimiter(db)
    key = "1.2.3.4|x'; DROP TABLE ratelimit_failures; --"
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert _count(db) == 1
    limiter.record_success(key)
    assert _count(db) == 0


def test_attempt_counts_before_the_credentials_are_checked(db: Database) -> None:
    clock = Clock()
    limiter = SqliteRateLimiter(db, free_attempts=1, base_delay=2.0, max_delay=60.0, clock=clock)
    key = "k"
    assert limiter.attempt(key) == 0.0
    assert limiter.attempt(key) == pytest.approx(2.0)
    assert limiter.retry_after(key) == pytest.approx(2.0)
    clock.now += 2.0
    assert limiter.attempt(key) == 0.0  # the blocked try above was not counted
    assert limiter.retry_after(key) == pytest.approx(4.0)
    limiter.record_success(key)
    assert limiter.retry_after(key) == 0.0


def test_attempt_never_lets_more_than_free_attempts_through(tmp_path: Path) -> None:
    """Parallel workers take their attempt in one transaction: exactly ``free_attempts``."""
    clock = Clock()
    path = tmp_path / "h.db"
    databases = [Database(path) for _ in range(8)]
    try:
        limiters = [
            SqliteRateLimiter(db, free_attempts=3, base_delay=60.0, clock=clock) for db in databases
        ]
        barrier = threading.Barrier(len(limiters))
        waits: list[float] = []
        lock = threading.Lock()

        def take(limiter: SqliteRateLimiter) -> None:
            barrier.wait()
            wait = limiter.attempt("k")
            with lock:
                waits.append(wait)

        threads = [threading.Thread(target=take, args=(limiter,)) for limiter in limiters]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(1 for wait in waits if wait == 0.0) == 3
    finally:
        for db in databases:
            db.close()


def _count(db: Database) -> int:
    with db.connection() as conn:
        row: sqlite3.Row = conn.execute("SELECT COUNT(*) FROM ratelimit_failures").fetchone()
        return int(row[0])
