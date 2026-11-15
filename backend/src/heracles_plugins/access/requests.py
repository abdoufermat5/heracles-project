"""Access requests: the state of each request, in the application database."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from heracles.ldap import dn as dnlib
from heracles.storage import Database

COMPONENT = "access_requests"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE access_requests (
        id TEXT PRIMARY KEY,
        directory_id TEXT NOT NULL,
        requester_dn TEXT NOT NULL,
        member_dn TEXT NOT NULL,
        member_key TEXT NOT NULL,
        target_dn TEXT NOT NULL,
        target_key TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        target_label TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL,
        until TEXT,
        status TEXT NOT NULL,
        created_at REAL NOT NULL,
        decided_by TEXT NOT NULL DEFAULT '',
        decided_at REAL,
        comment TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX access_requests_status ON access_requests (directory_id, status);
    CREATE INDEX access_requests_member ON access_requests (member_key);
    """,
    # reminders already sent (one per grant end date)
    """
    CREATE TABLE access_reminders (
        key TEXT PRIMARY KEY,
        sent_at REAL NOT NULL
    );
    """,
)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
CANCELLED = "cancelled"
FAILED = "failed"
STATUSES = (PENDING, APPROVED, REJECTED, CANCELLED, FAILED)

_COLUMNS = (
    "id, directory_id, requester_dn, member_dn, target_dn, target_kind, target_label, reason,"
    " until, status, created_at, decided_by, decided_at, comment, error"
)


_SELECT = "SELECT " + _COLUMNS + " FROM access_requests"  # noqa: S608 (constant columns)
_INSERT = (
    "INSERT INTO access_requests (" + _COLUMNS + ", member_key, target_key)"  # noqa: S608
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(frozen=True, slots=True)
class AccessRequest:
    id: str
    directory_id: str
    requester_dn: str
    member_dn: str
    target_dn: str
    target_kind: str  # membership attribute: member or roleOccupant
    target_label: str
    reason: str
    until: str | None  # ISO date-time (UTC), or None for no end date
    status: str
    created_at: float
    decided_by: str = ""
    decided_at: float | None = None
    comment: str = ""
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requester": self.requester_dn,
            "member": self.member_dn,
            "target": {"dn": self.target_dn, "kind": self.target_kind, "label": self.target_label},
            "reason": self.reason,
            "until": self.until,
            "status": self.status,
            "created_at": self.created_at,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "comment": self.comment,
            "error": self.error,
        }


def _row(row: Any) -> AccessRequest:
    decided = row["decided_at"]
    return AccessRequest(
        id=row["id"],
        directory_id=row["directory_id"],
        requester_dn=row["requester_dn"],
        member_dn=row["member_dn"],
        target_dn=row["target_dn"],
        target_kind=row["target_kind"],
        target_label=row["target_label"] or "",
        reason=row["reason"],
        until=row["until"],
        status=row["status"],
        created_at=float(row["created_at"]),
        decided_by=row["decided_by"] or "",
        decided_at=None if decided is None else float(decided),
        comment=row["comment"] or "",
        error=row["error"] or "",
    )


class AccessRequestStore:
    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = database
        self._clock = clock
        database.migrate(COMPONENT, MIGRATIONS)

    def add(
        self,
        *,
        directory_id: str,
        requester_dn: str,
        member_dn: str,
        target_dn: str,
        target_kind: str,
        target_label: str,
        reason: str,
        until: str | None,
    ) -> AccessRequest:
        request = AccessRequest(
            id=secrets.token_hex(8),
            directory_id=directory_id,
            requester_dn=requester_dn,
            member_dn=member_dn,
            target_dn=target_dn,
            target_kind=target_kind,
            target_label=target_label,
            reason=reason,
            until=until,
            status=PENDING,
            created_at=self._clock(),
        )
        with self._db.transaction() as conn:
            conn.execute(
                _INSERT,
                (
                    request.id,
                    directory_id,
                    requester_dn,
                    member_dn,
                    target_dn,
                    target_kind,
                    target_label,
                    reason,
                    until,
                    PENDING,
                    request.created_at,
                    "",
                    None,
                    "",
                    "",
                    dnlib.normalize(member_dn),
                    dnlib.normalize(target_dn),
                ),
            )
        return request

    def get(self, request_id: str) -> AccessRequest | None:
        with self._db.connection() as conn:
            row = conn.execute(_SELECT + " WHERE id = ?", (request_id,)).fetchone()
        return _row(row) if row is not None else None

    def list(
        self,
        directory_id: str,
        *,
        status: str | None = None,
        member_dn: str | None = None,
        involving: str | None = None,
        limit: int = 500,
    ) -> list[AccessRequest]:
        """``member_dn``: asked for that person; ``involving``: that person is the member or
        the one who asked."""
        sql = _SELECT + " WHERE directory_id = ?"
        params: list[Any] = [directory_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        if member_dn:
            sql += " AND member_key = ?"
            params.append(dnlib.normalize(member_dn))
        if involving:
            sql += " AND (member_key = ? OR requester_dn = ?)"
            params.extend((dnlib.normalize(involving), involving))
        sql += " ORDER BY created_at DESC, id LIMIT ?"
        params.append(limit)
        with self._db.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row(r) for r in rows]

    def pending_for(
        self, directory_id: str, member_dn: str, target_dn: str
    ) -> AccessRequest | None:
        with self._db.connection() as conn:
            row = conn.execute(
                _SELECT + " WHERE directory_id = ? AND member_key = ? AND target_key = ?"
                " AND status = ?",
                (directory_id, dnlib.normalize(member_dn), dnlib.normalize(target_dn), PENDING),
            ).fetchone()
        return _row(row) if row is not None else None

    def decide(
        self, request: AccessRequest, status: str, *, by: str, comment: str = "", error: str = ""
    ) -> AccessRequest | None:
        """Move a pending request to ``status``; ``None`` when someone decided first."""
        now = self._clock()
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE access_requests SET status = ?, decided_by = ?, decided_at = ?,"
                " comment = ?, error = ? WHERE id = ? AND status = ?",
                (status, by, now, comment, error, request.id, PENDING),
            )
            if not cur.rowcount:
                return None
        return replace(
            request, status=status, decided_by=by, decided_at=now, comment=comment, error=error
        )

    def fail(self, request: AccessRequest, error: str) -> AccessRequest:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE access_requests SET status = ?, error = ? WHERE id = ?",
                (FAILED, error, request.id),
            )
        return replace(request, status=FAILED, error=error)

    # -- reminders --------------------------------------------------------------------------

    def claim_reminder(self, key: str) -> bool:
        """Note that the reminder ``key`` is being sent; ``False`` when it already was."""
        with self._db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO access_reminders (key, sent_at) VALUES (?, ?)"
                " ON CONFLICT (key) DO NOTHING",
                (key, self._clock()),
            )
            return bool(cur.rowcount or 0)

    def release_reminder(self, key: str) -> None:
        """Forget a claimed reminder whose mail could not be sent (the next pass retries)."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM access_reminders WHERE key = ?", (key,))

    def purge_reminders(self, older_than: float) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute("DELETE FROM access_reminders WHERE sent_at < ?", (older_than,))
            return int(cur.rowcount or 0)

    def reminder_keys(self) -> list[str]:
        with self._db.connection() as conn:
            rows = conn.execute("SELECT key FROM access_reminders ORDER BY key").fetchall()
        return [r["key"] for r in rows]


__all__ = [
    "APPROVED",
    "CANCELLED",
    "FAILED",
    "PENDING",
    "REJECTED",
    "STATUSES",
    "AccessRequest",
    "AccessRequestStore",
]
