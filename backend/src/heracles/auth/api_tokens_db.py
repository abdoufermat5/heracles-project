"""API tokens stored in the application database, shared by every worker process.

The row keeps the SHA-256 of the secret, never the secret. ``owner_key`` is the normalised
owner DN (listing and revoking do not depend on the letter case). ``types`` and
``allowed_ips`` are JSON lists.
Recording a use (:meth:`SqlApiTokenStore.touch`) is a single autocommit statement, outside
:meth:`~heracles.storage.Database.transaction` (on PostgreSQL that one takes a lock shared by
the whole cluster).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, cast

from heracles.auth.api_tokens import ApiToken
from heracles.ldap import dn as dnlib
from heracles.storage import Database

COMPONENT = "api_tokens"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE api_tokens (
        id TEXT PRIMARY KEY,
        owner_dn TEXT NOT NULL,
        owner_key TEXT NOT NULL,
        directory_id TEXT NOT NULL,
        name TEXT NOT NULL,
        scope TEXT NOT NULL,
        types TEXT NOT NULL DEFAULT '[]',
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        created_by TEXT NOT NULL,
        secret_hash TEXT NOT NULL,
        last_used_at REAL,
        last_used_ip TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX api_tokens_owner_key ON api_tokens (owner_key);
    CREATE INDEX api_tokens_expires_at ON api_tokens (expires_at);
    """,
    # 2026-11-16: networks the token may be used from (JSON list; empty: any address)
    "ALTER TABLE api_tokens ADD COLUMN allowed_ips TEXT NOT NULL DEFAULT '[]';",
    # 2026-11-16: identity of the owner entry (a re-created entry is another owner)
    "ALTER TABLE api_tokens ADD COLUMN owner_stamp TEXT NOT NULL DEFAULT '';",
)

_SELECT = (
    "SELECT id, owner_dn, directory_id, name, scope, types, created_at, expires_at, created_by,"
    " secret_hash, last_used_at, last_used_ip, allowed_ips, owner_stamp FROM api_tokens"
)
_INSERT = (
    "INSERT INTO api_tokens (id, owner_dn, directory_id, name, scope, types, created_at,"
    " expires_at, created_by, secret_hash, last_used_at, last_used_ip, owner_key, allowed_ips,"
    " owner_stamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _strings(raw: str | None) -> tuple[str, ...]:
    value: Any = json.loads(raw or "[]")
    items = cast("list[object]", value) if isinstance(value, list) else []
    return tuple(str(t) for t in items)


def _row(row: Any) -> ApiToken:
    types = _strings(row["types"])
    last = row["last_used_at"]
    return ApiToken(
        id=row["id"],
        owner_dn=row["owner_dn"],
        directory_id=row["directory_id"],
        name=row["name"],
        scope=row["scope"],
        types=types,
        created_at=float(row["created_at"]),
        expires_at=float(row["expires_at"]),
        created_by=row["created_by"],
        secret_hash=row["secret_hash"],
        last_used_at=None if last is None else float(last),
        last_used_ip=row["last_used_ip"] or "",
        allowed_ips=_strings(row["allowed_ips"]),
        owner_stamp=row["owner_stamp"] or "",
    )


class SqlApiTokenStore:
    """:class:`~heracles.auth.api_tokens.ApiTokenStore` on the application database."""

    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = database
        self._clock = clock
        database.migrate(COMPONENT, MIGRATIONS)

    def add(self, token: ApiToken) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                _INSERT,
                (
                    token.id,
                    token.owner_dn,
                    token.directory_id,
                    token.name,
                    token.scope,
                    json.dumps(list(token.types)),
                    token.created_at,
                    token.expires_at,
                    token.created_by,
                    token.secret_hash,
                    token.last_used_at,
                    token.last_used_ip,
                    dnlib.normalize(token.owner_dn),
                    json.dumps(list(token.allowed_ips)),
                    token.owner_stamp,
                ),
            )

    def get(self, token_id: str) -> ApiToken | None:
        with self._db.connection() as conn:
            row = conn.execute(_SELECT + " WHERE id = ?", (token_id,)).fetchone()
        return _row(row) if row is not None else None

    def list_for_owner(self, owner_dn: str) -> list[ApiToken]:
        with self._db.connection() as conn:
            rows = conn.execute(
                _SELECT + " WHERE owner_key = ? ORDER BY created_at, id",
                (dnlib.normalize(owner_dn),),
            ).fetchall()
        return [_row(r) for r in rows]

    def list_all(self) -> list[ApiToken]:
        with self._db.connection() as conn:
            rows = conn.execute(_SELECT + " ORDER BY created_at, id").fetchall()
        return [_row(r) for r in rows]

    def delete(self, token_id: str) -> bool:
        with self._db.transaction() as conn:
            cur = conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
            return bool(cur.rowcount)

    def delete_for_owner(self, owner_dn: str) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM api_tokens WHERE owner_key = ?", (dnlib.normalize(owner_dn),)
            )
            return int(cur.rowcount or 0)

    def touch(self, token_id: str, at: float, ip: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE api_tokens SET last_used_at = ?, last_used_ip = ? WHERE id = ?",
                (at, ip[:64], token_id),
            )

    def purge_expired(self, now: float) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute("DELETE FROM api_tokens WHERE expires_at <= ?", (now,))
            return int(cur.rowcount or 0)
