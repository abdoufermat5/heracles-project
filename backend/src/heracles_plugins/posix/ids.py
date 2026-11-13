"""Unix id allocation ("traditional" method) with collision-safe reservations.

The first free id is chosen from the directory contents, as the traditional method
says, but every chosen id is also *reserved* for a short time: two requests (or two
replicas sharing the application database) choosing at the same moment cannot hand
out the same id, because the id is only returned once its reservation is stored.
"""

from __future__ import annotations

import threading
import time
import weakref
from collections.abc import Callable
from typing import Any

from heracles.ldap.client import DirectoryClient, NoSuchObjectError
from heracles.ldap.filter import escape_filter_value
from heracles.storage import Database

#: Always considered taken (``nobody`` / ``nogroup``).
RESERVED_IDS = frozenset({65534})
MAX_ID = 2**32
#: How long an allocated-but-not-yet-written id stays reserved.
RESERVATION_TTL = 600.0

COMPONENT = "posix_ids"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE posix_id_reservations (
        kind TEXT NOT NULL,
        id INTEGER NOT NULL,
        reserved_at REAL NOT NULL,
        PRIMARY KEY (kind, id)
    );
    CREATE INDEX posix_id_reservations_age ON posix_id_reservations (reserved_at);
    """,
)


class IdAllocationError(RuntimeError):
    """No free id in the configured range."""


def parse_range(spec: str | int) -> tuple[int, int]:
    """``"1100"`` → (1100, 2**32); ``"1100-2000"`` → (1100, 2000)."""
    text = str(spec).strip()
    low, sep, high = text.partition("-")
    base = int(low)
    return base, (int(high) if sep and high.strip() else MAX_ID)


def used_ids(directory: DirectoryClient, object_class: str, attr: str) -> set[int]:
    """Every numeric ``attr`` value on entries of ``object_class`` under the base."""
    found: set[int] = set(RESERVED_IDS)
    flt = f"(&(objectClass={escape_filter_value(object_class)})({attr}=*))"
    try:
        for entry in directory.search(directory.base_dn, flt, attrs=[attr]):
            for value in entry.texts(attr):
                if value.strip().isdigit():
                    found.add(int(value))
    except NoSuchObjectError:
        pass
    return found


class IdReservations:
    """Short-lived reservations of allocated ids, in the application database.

    Without a database (demo, tests) the reservations live in this process, guarded
    by a lock: enough to make concurrent requests safe, not concurrent replicas. The
    database path uses one transaction per reservation, so the whole cluster serialises
    on it. Expired rows are skipped (and dropped) the next time the kind is read.
    ``kind`` is the id attribute name (``uidNumber`` / ``gidNumber``).
    """

    def __init__(
        self,
        database: Database | None = None,
        *,
        ttl: float = RESERVATION_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db = database
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._memory: dict[tuple[str, int], float] = {}
        if database is not None:
            database.migrate(COMPONENT, MIGRATIONS)

    def taken(self, kind: str) -> set[int]:
        """Ids of ``kind`` reserved less than ``ttl`` ago."""
        now = self._clock()
        stale = now - self._ttl
        if self._db is None:
            with self._lock:
                self._drop_memory(stale)
                return {ident for k, ident in self._memory if k == kind}
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM posix_id_reservations WHERE reserved_at <= ?", (stale,))
            rows = conn.execute(
                "SELECT id FROM posix_id_reservations WHERE kind = ? AND reserved_at > ?",
                (kind, stale),
            ).fetchall()
        return {int(row["id"]) for row in rows}

    def reserve(self, kind: str, ident: int) -> bool:
        """Reserve ``kind``/``ident``; False when another caller holds it."""
        now = self._clock()
        stale = now - self._ttl
        if self._db is None:
            with self._lock:
                self._drop_memory(stale)
                if (kind, ident) in self._memory:
                    return False
                self._memory[(kind, ident)] = now
                return True
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT reserved_at FROM posix_id_reservations WHERE kind = ? AND id = ?",
                (kind, ident),
            ).fetchone()
            if row is not None and float(row["reserved_at"]) > stale:
                return False
            conn.execute(
                "INSERT INTO posix_id_reservations (kind, id, reserved_at) VALUES (?, ?, ?)"
                " ON CONFLICT (kind, id) DO UPDATE SET reserved_at = excluded.reserved_at",
                (kind, ident, now),
            )
            return True

    def _drop_memory(self, stale: float) -> None:
        for key in [k for k, at in self._memory.items() if at <= stale]:
            del self._memory[key]


_reservations_lock = threading.Lock()
_reservations: dict[int, tuple[Database, IdReservations]] = {}
#: Without an application database, reservations are per registry (tests, demo, single process);
#: a weak key keeps them from outliving the registry.
_registry_reservations: weakref.WeakKeyDictionary[Any, IdReservations] = weakref.WeakKeyDictionary()


def reservations_of(registry: Any) -> IdReservations:
    """The reservation table of the registry's application database (in memory without one)."""
    database: Database | None = getattr(registry, "database", None)
    with _reservations_lock:
        if database is None:
            found = _registry_reservations.get(registry)
            if found is None:
                found = IdReservations()
                _registry_reservations[registry] = found
            return found
        slot = id(database)
        entry = _reservations.get(slot)
        if entry is None or entry[0] is not database:
            entry = (database, IdReservations(database))
            _reservations[slot] = entry
        return entry[1]


def next_free_id(
    directory: DirectoryClient,
    object_class: str,
    attr: str,
    *,
    base: str | int,
    min_id: int = 0,
    reserved: set[int] | None = None,
    reservations: IdReservations | None = None,
) -> int:
    """First free id strictly greater than the range base (and ≥ ``min_id``).

    With ``reservations`` the candidate is reserved before it is returned; a candidate
    another caller reserved in between is skipped, so concurrent callers get distinct ids.
    """
    low, high = parse_range(base)
    taken = used_ids(directory, object_class, attr) | (reserved or set())
    if reservations is not None:
        taken |= reservations.taken(attr)
    candidate = max(low + 1, min_id)
    while candidate < high:
        if candidate not in taken and (
            reservations is None or reservations.reserve(attr, candidate)
        ):
            return candidate
        candidate += 1
    raise IdAllocationError(f"no free {attr} in range {low}-{high}")
