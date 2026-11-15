"""The component stores on both backends (PostgreSQL when ``HERACLES_TEST_POSTGRES_URL`` is set).

Run once against a throwaway server::

    docker run -d --name hrc-pg-test -p 55432:5432 -e POSTGRES_PASSWORD=t postgres:17
    HERACLES_TEST_POSTGRES_URL=postgresql://postgres:t@localhost:55432/postgres pytest tests/storage
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest

from heracles.auth.ratelimit_db import SqliteRateLimiter
from heracles.auth.second_factor import WebAuthnCredential
from heracles.auth.second_factor_db import SqliteSecondFactorStore
from heracles.auth.sessions_db import SqliteSessionStore
from heracles.objects.activation import PluginOverrideStore
from heracles.storage import Database, DatabaseError, Migration
from heracles.tasks.scheduler import RunRecord, TaskStore

PG_URL = os.environ.get("HERACLES_TEST_POSTGRES_URL")
DN = "uid=jdoe,ou=people,dc=example,dc=com"

MakeDb = Callable[[], Database]


@pytest.fixture(params=["sqlite", "postgresql"])
def make_db(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[MakeDb]:
    """A factory of ``Database`` objects on one shared, empty database (like two replicas)."""
    opened: list[Database] = []
    if request.param == "sqlite":
        path = tmp_path / "h.db"

        def sqlite_db() -> Database:
            opened.append(Database(path))
            return opened[-1]

        yield sqlite_db
    else:
        if not PG_URL:
            pytest.skip("HERACLES_TEST_POSTGRES_URL is not set")
        import psycopg

        schema = f"t_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(PG_URL, autocommit=True) as admin:
            admin.execute(cast("Any", f"CREATE SCHEMA {schema}"))
        sep = "&" if "?" in PG_URL else "?"
        url = f"{PG_URL}{sep}options={quote(f'-csearch_path={schema}')}"

        def pg_db() -> Database:
            opened.append(Database(url))
            return opened[-1]

        yield pg_db
        for db in opened:
            db.close()
        with psycopg.connect(PG_URL, autocommit=True) as admin:
            admin.execute(cast("Any", f"DROP SCHEMA {schema} CASCADE"))
        return
    for db in opened:
        db.close()


def test_migrations_translate_and_variants(make_db: MakeDb) -> None:
    db = make_db()
    plain = "CREATE TABLE a (id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL NOT NULL, b BLOB);"
    variant = Migration(
        sqlite="CREATE TABLE v (x INTEGER);", postgresql="CREATE TABLE v (x BIGINT);"
    )
    assert db.migrate("demo", [plain, variant]) == 2
    assert db.migrate("demo", [plain, variant]) == 2
    with db.transaction() as conn:
        conn.execute("INSERT INTO a (t, b) VALUES (?, ?)", (1700000000.123456, b"\x00\x01"))
        conn.execute("INSERT INTO v (x) VALUES (?)", (5,))
    with db.connection() as conn:
        row = conn.execute("SELECT id, t, b FROM a").fetchone()
    assert (row["id"], row["t"], bytes(row["b"])) == (1, 1700000000.123456, b"\x00\x01")
    assert row[1] == row["t"]


def test_newer_schema_is_refused(make_db: MakeDb) -> None:
    make_db().migrate("demo", ["CREATE TABLE a (x INTEGER);", "CREATE TABLE b (x INTEGER);"])
    with pytest.raises(DatabaseError, match="newer than this server"):
        make_db().migrate("demo", ["CREATE TABLE a (x INTEGER);"])


def test_transaction_rolls_back_and_serialises(make_db: MakeDb) -> None:
    db = make_db()
    db.migrate("demo", ["CREATE TABLE c (n INTEGER NOT NULL);"])
    with db.transaction() as conn:
        conn.execute("INSERT INTO c VALUES (0)")
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("UPDATE c SET n = 99")
        raise RuntimeError("boom")

    def bump(own: Database) -> None:
        for _ in range(10):
            with own.transaction() as conn:  # read-then-write must not interleave
                n = conn.execute("SELECT n FROM c").fetchone()[0]
                conn.execute("UPDATE c SET n = ?", (n + 1,))

    others = [make_db(), make_db()]
    threads = [threading.Thread(target=bump, args=(d,)) for d in others]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with db.connection() as conn:
        assert conn.execute("SELECT n FROM c").fetchone()[0] == 20


def test_task_lease_is_exclusive_across_replicas(make_db: MakeDb) -> None:
    first, second = TaskStore(make_db()), TaskStore(make_db())
    assert first.acquire_lease("a", 60) is True
    assert second.acquire_lease("b", 60) is False
    first.release_lease("a")
    assert second.acquire_lease("b", 60) is True
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    first.record(RunRecord("d", "r", "k", now, now, "ok", {"n": 1}, ["e"]))
    (run,) = second.recent()
    assert (run.runner, dict(run.counts), list(run.errors)) == ("r", {"n": 1}, ["e"])
    assert run.id == 1


def test_plugin_switches_are_shared(make_db: MakeDb) -> None:
    first, second = PluginOverrideStore(make_db()), PluginOverrideStore(make_db())
    first.set("sudo", False, "admin")
    first.set("sudo", True, "admin")
    first.set("ssh", False)
    assert second.load() == {"sudo": True, "ssh": False}


def test_sessions_are_shared(make_db: MakeDb) -> None:
    kwargs: dict[str, Any] = {"idle_timeout": 600.0, "absolute_timeout": 3600.0}
    first, second = SqliteSessionStore(make_db(), **kwargs), SqliteSessionStore(make_db(), **kwargs)
    session = first.create(DN, "main")
    seen = second.get(session.id)
    assert seen is not None and seen.user_dn == DN
    second.delete(session.id)
    assert first.get(session.id) is None


def test_second_factor_blobs_and_upserts(make_db: MakeDb) -> None:
    store = SqliteSecondFactorStore(make_db())
    store.set_totp_secret(DN, "S")
    store.set_totp_secret(DN, "T")
    store.set_last_totp_step(DN, 41_000_000)
    assert (store.totp_secret(DN), store.last_totp_step(DN)) == ("T", 41_000_000)
    store.set_recovery_hashes(DN, ["b", "a", "a"])
    assert sorted(store.recovery_hashes(DN)) == ["a", "b"]
    assert store.consume_recovery_hash(DN, "a") is True
    assert store.consume_recovery_hash(DN, "a") is False
    store.add_webauthn_credential(DN, WebAuthnCredential(b"k1", b"pk1", 0, "Desk"))
    store.update_sign_count(DN, b"k1", 7)
    (cred,) = store.webauthn_credentials(DN)
    assert (cred.credential_id, cred.public_key, cred.sign_count) == (b"k1", b"pk1", 7)
    assert store.remove_webauthn_credential(DN, b"k1") is True


def test_rate_limit_is_shared(make_db: MakeDb) -> None:
    now = [1_000_000.0]
    first = SqliteRateLimiter(make_db(), free_attempts=1, clock=lambda: now[0])
    second = SqliteRateLimiter(make_db(), free_attempts=1, clock=lambda: now[0])
    key = first.key("10.0.0.1", "jdoe")
    first.record_failure(key)
    first.record_failure(key)
    assert second.retry_after(key) > 0


def test_listing_snapshot_dies_when_another_replica_writes(make_db: MakeDb) -> None:
    from heracles.ldap.client import Entry, Scope
    from heracles.objects.listing_cache import ListingCache, ListingScope
    from heracles.objects.listing_epochs import ListingEpochs

    a, b = ListingEpochs(make_db()), ListingEpochs(make_db())
    cache = ListingCache()  # replica B's process-local cache
    acl = object()

    def scope() -> ListingScope:  # one per request, as Domain.service builds it
        return ListingScope(cache, "sid", acl, lambda: b.current("sid"))

    first = scope()
    key = first.key("user", "dc=x", Scope.SUBTREE, "", "uid", False, ())
    first.put(key, [Entry("uid=a,dc=x", {})])
    assert scope().get(key) is not None
    a.bump("sid")  # the same session writes through replica A
    assert scope().get(key) is None


def test_copy_sqlite_into_postgres(tmp_path: Path, make_db: MakeDb) -> None:
    from datetime import UTC, datetime

    from heracles.storage.copy import copy_sqlite_to_postgres

    target = make_db()
    if target.dialect != "postgresql":
        pytest.skip("PostgreSQL only")
    source = tmp_path / "old.db"
    old = Database(source)
    stamp = datetime.now(UTC)
    TaskStore(old).record(RunRecord("d", "r", "k", stamp, stamp, "ok"))
    PluginOverrideStore(old).set("sudo", False)
    SqliteSecondFactorStore(old).add_webauthn_credential(DN, WebAuthnCredential(b"k", b"p", 1, ""))
    old.close()
    copied = copy_sqlite_to_postgres(source, target.url)  # type: ignore[attr-defined]
    assert copied["task_runs"] == 1 and copied["plugin_overrides"] == 1
    assert PluginOverrideStore(target).load() == {"sudo": False}
    TaskStore(target).record(RunRecord("d", "r2", "k", stamp, stamp, "ok"))  # serial moved on
    assert [r.id for r in TaskStore(target).recent()] == [2, 1]


def test_api_tokens_are_shared_between_replicas(make_db: MakeDb) -> None:
    from heracles.auth import api_tokens
    from heracles.auth.api_tokens_db import SqlApiTokenStore

    one, two = SqlApiTokenStore(make_db()), SqlApiTokenStore(make_db())
    new = api_tokens.generate(
        owner_dn=DN,
        directory_id="main",
        name="ci",
        scope="write",
        types=("user", "group"),
        expires_at=5000.0,
        created_by=DN,
        now=1000.0,
    )
    old = api_tokens.generate(
        owner_dn=DN.upper(),
        directory_id="main",
        name="old",
        scope="read",
        types=(),
        expires_at=1500.0,
        created_by=DN,
        now=1000.0,
    )
    one.add(new.token)
    one.add(old.token)
    seen = two.get(new.token.id)
    assert seen == new.token and seen is not None and seen.types == ("group", "user")
    assert {t.id for t in two.list_for_owner(DN)} == {new.token.id, old.token.id}
    two.touch(new.token.id, 1200.0, "192.0.2.9")
    touched = one.get(new.token.id)
    assert touched is not None and touched.last_used_at == 1200.0
    assert two.purge_expired(2000.0) == 1
    assert one.delete(new.token.id) and not two.delete(new.token.id)
    one.add(old.token)
    assert two.delete_for_owner(DN) == 1 and one.list_all() == []


def test_access_request_store(make_db: MakeDb) -> None:
    from heracles_plugins.access.requests import APPROVED, PENDING, AccessRequestStore

    store = AccessRequestStore(make_db(), clock=lambda: 1000.0)
    created = store.add(
        directory_id="main",
        requester_dn=DN,
        member_dn=DN,
        target_dn="cn=devs,dc=example,dc=com",
        target_kind="member",
        target_label="devs",
        reason="needed",
        until="2030-01-01T23:59:59+00:00",
    )
    other = AccessRequestStore(make_db())  # a second replica sees it
    assert other.pending_for("main", DN.upper(), "CN=devs,dc=example,dc=com") == created
    assert [r.id for r in other.list("main", status=PENDING)] == [created.id]
    done = store.decide(created, APPROVED, by="uid=boss,dc=example,dc=com", comment="ok")
    assert done is not None and done.status == APPROVED
    assert store.decide(created, APPROVED, by="x") is None  # decided once
    assert other.get(created.id) == done
    assert other.list("main", member_dn=DN)[0].until == "2030-01-01T23:59:59+00:00"


def test_access_request_for_someone_else_and_orphan_cancel(make_db: MakeDb) -> None:
    from heracles_plugins.access.requests import CANCELLED, PENDING, AccessRequestStore

    store = AccessRequestStore(make_db(), clock=lambda: 1000.0)
    boss = "uid=boss,ou=people,dc=example,dc=com"
    created = store.add(
        directory_id="main",
        requester_dn=boss,
        member_dn=DN,
        target_dn="cn=devs,dc=example,dc=com",
        target_kind="member",
        target_label="devs",
        reason="joins",
        until=None,
    )
    other = AccessRequestStore(make_db())
    # both the person and the one who asked find it; nobody else
    assert [r.id for r in other.list("main", involving=DN.upper())] == [created.id]
    assert [r.id for r in other.list("main", involving=boss)] == [created.id]
    assert other.list("main", involving="uid=x,dc=example,dc=com") == []
    assert other.list("main", member_dn=boss) == []
    # the scheduler cancels it when the target is gone (no author)
    done = other.decide(created, CANCELLED, by="", comment="the group or role no longer exists")
    assert done is not None and done.status == CANCELLED and done.decided_by == ""
    assert store.list("main", status=PENDING) == []
    assert store.get(created.id) == done


def test_access_reminders_are_claimed_once(make_db: MakeDb) -> None:
    from heracles_plugins.access.requests import AccessRequestStore

    first = "main|cn=devs,dc=example,dc=com|member|uid=ann|20300101000000Z"
    second = "main|cn=devs,dc=example,dc=com|member|uid=ann|20300201000000Z"
    one = AccessRequestStore(make_db(), clock=lambda: 1000.0)
    two = AccessRequestStore(make_db(), clock=lambda: 2000.0)  # a second replica
    assert one.claim_reminder(first)
    assert not two.claim_reminder(first)
    assert two.claim_reminder(second)
    assert one.reminder_keys() == [first, second]
    # old rows are purged; a mail that could not be sent is released and claimed again
    assert one.purge_reminders(1500.0) == 1 and one.reminder_keys() == [second]
    assert one.claim_reminder(first)
    one.release_reminder(first)
    assert two.claim_reminder(first) and not one.claim_reminder(first)


def test_access_review_store(make_db: MakeDb) -> None:
    from heracles_plugins.access import reviews as rv

    store = rv.ReviewStore(make_db(), clock=lambda: 1000.0)
    campaign = rv.new_campaign(
        directory_id="main",
        name="Q4",
        creator=DN,
        deadline=2000.0,
        rule="owner",
        default=rv.KEEP,
        selector={"holders": ["cn=devs"], "base": ""},
        now=1000.0,
    )
    item = rv.Item(campaign.id, "i1", "cn=devs", "devs", "member", "uid=ann", reviewer_dn=DN)
    store.create(campaign, [item])
    other = rv.ReviewStore(make_db())
    assert other.get(campaign.id) == campaign
    assert [i.item_id for i in other.items_for_reviewer(DN.upper())] == ["i1"]
    store.decide(item, rv.REVOKE, "gone", DN)
    store.set_outcome(item, "revoked")
    assert other.items(campaign.id)[0].outcome == "revoked"
    closing = store.move(campaign, rv.OPEN, rv.CLOSING)
    assert closing is not None and store.move(campaign, rv.OPEN, rv.CLOSING) is None
    closed = store.move(
        closing, rv.CLOSING, rv.CLOSED, closed_by=DN, closed_at=1500.0, report_hash="ab"
    )
    assert closed is not None and other.get(campaign.id) == closed
