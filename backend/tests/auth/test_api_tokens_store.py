"""API token stores: the in-memory one and the one on the application database."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from heracles.auth import api_tokens
from heracles.auth.api_tokens import ApiTokenStore, InMemoryApiTokenStore
from heracles.auth.api_tokens_db import SqlApiTokenStore
from heracles.storage import Database

OWNER = "uid=jdoe,ou=people,dc=example,dc=com"


def _memory(_: Path) -> ApiTokenStore:
    return InMemoryApiTokenStore()


def _sqlite(tmp: Path) -> ApiTokenStore:
    return SqlApiTokenStore(Database(tmp / "heracles.db"))


@pytest.fixture(params=[_memory, _sqlite], ids=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ApiTokenStore:
    factory: Callable[[Path], ApiTokenStore] = request.param
    return factory(tmp_path)


def _new(
    owner: str = OWNER, *, expires: float = 2000.0, types: tuple[str, ...] = ()
) -> api_tokens.NewToken:
    return api_tokens.generate(
        owner_dn=owner,
        directory_id="main",
        name="ci",
        scope="write",
        types=types,
        expires_at=expires,
        created_by=owner,
        now=1000.0,
    )


def test_round_trip_and_verify(store: ApiTokenStore) -> None:
    new = _new(types=("user", "group"))
    secret, created = new.secret, new.token
    store.add(created)
    parsed = api_tokens.parse(secret)
    assert parsed is not None and parsed[0] == created.id
    loaded = store.get(created.id)
    assert loaded is not None and loaded == created
    assert api_tokens.verify(loaded, parsed[1])
    assert not api_tokens.verify(loaded, "x" * 43)
    assert loaded.types == ("group", "user")


def test_owner_lookup_ignores_case_and_revokes(store: ApiTokenStore) -> None:
    store.add(_new().token)
    store.add(_new().token)
    store.add(_new("uid=other,dc=example,dc=com").token)
    assert len(store.list_for_owner(OWNER.upper())) == 2
    assert len(store.list_all()) == 3
    assert store.delete_for_owner(OWNER) == 2
    assert [t.owner_dn for t in store.list_all()] == ["uid=other,dc=example,dc=com"]


def test_touch_and_purge(store: ApiTokenStore) -> None:
    old = _new(expires=1500.0).token
    live = _new(expires=5000.0).token
    store.add(old)
    store.add(live)
    store.touch(live.id, 1200.0, "192.0.2.1")
    touched = store.get(live.id)
    assert touched is not None and touched.last_used_at == 1200.0
    assert touched.last_used_ip == "192.0.2.1"
    assert store.purge_expired(2000.0) == 1
    assert store.get(old.id) is None and store.delete(live.id)
    assert not store.delete(live.id)


def test_scope_levels() -> None:
    token = _new().token
    assert token.allows("read") and token.allows("write") and not token.allows("admin")
    with pytest.raises(ValueError):
        api_tokens.generate(
            owner_dn=OWNER,
            directory_id="main",
            name="x",
            scope="root",
            types=(),
            expires_at=1.0,
            created_by=OWNER,
            now=0.0,
        )


def test_allowed_networks_round_trip_and_match(store: ApiTokenStore) -> None:
    created = api_tokens.generate(
        owner_dn=OWNER,
        directory_id="main",
        name="ci",
        scope="read",
        types=(),
        expires_at=2000.0,
        created_by=OWNER,
        now=1000.0,
        allowed_ips=[" 10.1.0.0/16 ", "192.0.2.7", "2001:db8::/32", "10.1.2.3/16"],
    ).token
    # canonical networks, an address alone is a host network, duplicates folded
    assert created.allowed_ips == ("10.1.0.0/16", "192.0.2.7/32", "2001:db8::/32")
    store.add(created)
    loaded = store.get(created.id)
    assert loaded is not None and loaded.allowed_ips == created.allowed_ips
    assert loaded.allows_ip("10.1.200.4") and loaded.allows_ip("2001:db8::1")
    assert not loaded.allows_ip("10.2.0.1") and not loaded.allows_ip("not-an-address")
    assert loaded.allows_ip("::ffff:10.1.2.3")  # an IPv4 client seen through an IPv6 socket
    assert _new().token.allows_ip("203.0.113.9")  # no list: any address


def test_bad_networks_are_refused() -> None:
    with pytest.raises(ValueError, match="nope"):
        api_tokens.normalize_networks(["10.0.0.0/8", "nope"])


def test_a_database_of_the_first_schema_gains_the_column(tmp_path: Path) -> None:
    from heracles.auth.api_tokens_db import COMPONENT, MIGRATIONS

    database = Database(tmp_path / "heracles.db")
    database.migrate(COMPONENT, MIGRATIONS[:1])
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO api_tokens (id, owner_dn, owner_key, directory_id, name, scope,"
            " created_at, expires_at, created_by, secret_hash)"
            " VALUES ('0123456789abcdef', ?, ?, 'main', 'old', 'read', 1, 2, ?, 'h')",
            (OWNER, OWNER.lower(), OWNER),
        )
    old = SqlApiTokenStore(database).get("0123456789abcdef")
    assert old is not None and old.allowed_ips == () and old.allows_ip("198.51.100.1")
