"""Sessions stored in the application database, shared by every worker process.

A session row holds the scalar fields of :class:`~heracles.auth.sessions.Session` plus its
``cache`` as JSON (never pickle). The row key is the SHA-256 of the session id, so a leaked
database does not hand out live cookies. ``user_dn`` keeps the DN as the directory spells
it; ``user_key`` holds its normalised form, so listing and revoking a person's sessions
does not depend on the letter case.

Handlers mutate the session they got from :meth:`SqliteSessionStore.get` in place, so a
change only reaches the other processes through :meth:`SqliteSessionStore.save` (the API
layer calls it at the end of each request). ``save`` writes the *difference* against what
was loaded, merged into the current row: two requests of one session on different
processes do not overwrite each other's keys, a second-factor failure is counted rather
than overwritten, and a session deleted or rotated meanwhile is not brought back.

Cache values are persisted when they are JSON-representable: ``None``/``bool``/``int``/
``float``/``str``, lists, ``str``-keyed dicts, plus ``bytes`` and ``tuple`` which are
tagged (``{"$b": base64}``, ``{"$t": [...]}``). Anything else (the derived ACL resolution,
for one) stays in a per-process side cache; the row only carries a random token for it
(``{"$local": token}``). A process that holds the value under that token uses it; every
other process sees the key as absent and recomputes. Removing the key (cache
invalidation) removes the token, so the invalidation reaches every process.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, cast

from heracles.auth.sessions import CLIENT_KEY, Session, SessionInfo
from heracles.ldap import dn as dnlib
from heracles.storage import Database

COMPONENT = "sessions"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE sessions (
        id_hash TEXT PRIMARY KEY,
        user_dn TEXT NOT NULL,
        directory_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        last_seen REAL NOT NULL,
        second_factor_pending INTEGER NOT NULL DEFAULT 0,
        second_factor_methods TEXT NOT NULL DEFAULT '[]',
        second_factor_failures INTEGER NOT NULL DEFAULT 0,
        cache TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX sessions_last_seen ON sessions (last_seen);
    CREATE INDEX sessions_created_at ON sessions (created_at);
    """,
    # ``user_dn`` keeps the DN as the directory spells it; ``user_key`` is its normalised
    # form, so listing and revoking a person's sessions does not depend on the letter case.
    """
    ALTER TABLE sessions ADD COLUMN user_key TEXT;
    CREATE INDEX sessions_user_key ON sessions (user_key);
    """,
)

_SELECT = (
    "SELECT user_dn, directory_id, created_at, last_seen, second_factor_pending,"
    " second_factor_methods, second_factor_failures, cache"
    " FROM sessions WHERE id_hash = ?"
)

_BYTES = "$b"
_TUPLE = "$t"
_LOCAL = "$local"

#: Sessions whose process-local values are remembered; the oldest are forgotten first
#: (values of sessions that ended on another process would otherwise linger).
SIDE_CACHE_SESSIONS = 4096


class _NotPersistableError(Exception):
    """A cache value cannot be stored as JSON."""


def _encode(value: object) -> Any:
    kind = type(value)
    if value is None or kind in (bool, str, int):
        return value
    if kind is float:
        if not math.isfinite(cast("float", value)):
            raise _NotPersistableError
        return value
    if kind is bytes:
        return {_BYTES: base64.urlsafe_b64encode(cast("bytes", value)).decode("ascii")}
    if kind is tuple:
        return {_TUPLE: [_encode(v) for v in cast("tuple[object, ...]", value)]}
    if kind is list:
        return [_encode(v) for v in cast("list[object]", value)]
    if kind is dict:
        out: dict[str, Any] = {}
        for key, item in cast("dict[object, object]", value).items():
            # "$"-prefixed keys are the tags above: keep the encoding unambiguous.
            if type(key) is not str or key.startswith("$"):
                raise _NotPersistableError
            out[key] = _encode(item)
        return out
    raise _NotPersistableError


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(v) for v in cast("list[Any]", value)]
    if isinstance(value, dict):
        items = cast("dict[str, Any]", value)
        if len(items) == 1:
            (tag, inner), *_ = items.items()
            if tag == _BYTES:
                return base64.urlsafe_b64decode(cast("str", inner))
            if tag == _TUPLE:
                return tuple(_decode(v) for v in cast("list[Any]", inner))
        return {k: _decode(v) for k, v in items.items()}
    return value


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _local_token(encoded: Any) -> str | None:
    if isinstance(encoded, dict):
        items = cast("dict[str, Any]", encoded)
        if len(items) == 1 and _LOCAL in items:
            return str(items[_LOCAL])
    return None


def _digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class _State:
    """What a session looked like when it was loaded or last saved."""

    pending: bool
    methods: str  # JSON
    failures: int
    #: key -> JSON of its encoded value (local values: of the token marker).
    cache: dict[str, str]


class SqliteSessionStore:
    """:class:`~heracles.auth.sessions.SessionStore` on the application database."""

    def __init__(
        self,
        database: Database,
        *,
        idle_timeout: float,
        absolute_timeout: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db = database
        self._idle = idle_timeout
        self._absolute = absolute_timeout
        self._clock = clock
        #: session key -> cache key -> (token, value) for values that cannot be stored.
        self._side: OrderedDict[str, dict[str, tuple[str, Any]]] = OrderedDict()
        self._side_lock = threading.Lock()
        database.migrate(COMPONENT, MIGRATIONS)
        self._backfill_user_keys()

    def _backfill_user_keys(self) -> None:
        """Key rows written before the column existed: normalising a DN is not SQL."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id_hash, user_dn FROM sessions WHERE user_key IS NULL"
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE sessions SET user_key = ? WHERE id_hash = ?",
                    (dnlib.normalize(row["user_dn"]), row["id_hash"]),
                )

    @property
    def idle_timeout(self) -> float:
        """Seconds of inactivity after which a session expires (changeable at runtime)."""
        return self._idle

    @idle_timeout.setter
    def idle_timeout(self, seconds: float) -> None:
        self._idle = seconds

    # -- process-local values ------------------------------------------------------------------
    def _side_get(self, key: str) -> dict[str, tuple[str, Any]]:
        with self._side_lock:
            entry = self._side.get(key)
            if entry is None:
                return {}
            self._side.move_to_end(key)
            return dict(entry)

    def _side_update(self, key: str, put: dict[str, tuple[str, Any]], drop: Iterable[str]) -> None:
        with self._side_lock:
            entry = self._side.setdefault(key, {})
            for name in drop:
                entry.pop(name, None)
            entry.update(put)
            if not entry:
                del self._side[key]
                return
            self._side.move_to_end(key)
            while len(self._side) > SIDE_CACHE_SESSIONS:
                self._side.popitem(last=False)

    def _side_drop(self, key: str) -> None:
        with self._side_lock:
            self._side.pop(key, None)

    # -- helpers -------------------------------------------------------------------------------
    def _expired(self, row: Any, now: float) -> bool:
        return (
            now - float(row["last_seen"]) > self._idle
            or now - float(row["created_at"]) > self._absolute
        )

    def _loaded(self, row: Any, session_id: str, key: str, last_seen: float) -> Session:
        stored = cast("dict[str, Any]", json.loads(row["cache"]))
        local = self._side_get(key)
        cache: dict[str, Any] = {}
        known: dict[str, str] = {}
        for name, encoded in stored.items():
            token = _local_token(encoded)
            if token is None:
                cache[name] = _decode(encoded)
            else:
                mine = local.get(name)
                if mine is None or mine[0] != token:
                    # Another process's value (or a stale one): absent here, left untouched.
                    continue
                cache[name] = mine[1]
            known[name] = _dump(encoded)
        methods = cast("list[str]", json.loads(row["second_factor_methods"]))
        pending = bool(row["second_factor_pending"])
        failures = int(row["second_factor_failures"])
        session = Session(
            id=session_id,
            user_dn=row["user_dn"],
            directory_id=row["directory_id"],
            created_at=float(row["created_at"]),
            last_seen=last_seen,
            second_factor_pending=pending,
            second_factor_methods=methods,
            second_factor_failures=failures,
            cache=cache,
        )
        session.persisted = _State(pending, _dump(methods), failures, known)
        return session

    def _state_of(
        self, key: str, session: Session
    ) -> tuple[_State, dict[str, tuple[str, Any]], dict[str, Any]]:
        """The persistable view of ``session``: state, its local values, key -> encoded."""
        known = self._side_get(key)
        encoded: dict[str, Any] = {}
        local: dict[str, tuple[str, Any]] = {}
        for name, value in session.cache.items():
            try:
                encoded[name] = _encode(value)
            except _NotPersistableError:
                previous = known.get(name)
                token = (
                    previous[0]
                    if previous is not None and previous[1] is value
                    else secrets.token_hex(8)
                )
                encoded[name] = {_LOCAL: token}
                local[name] = (token, value)
        state = _State(
            session.second_factor_pending,
            _dump(list(session.second_factor_methods)),
            session.second_factor_failures,
            {name: _dump(value) for name, value in encoded.items()},
        )
        return state, local, encoded

    # -- SessionStore --------------------------------------------------------------------------
    def create(
        self,
        user_dn: str,
        directory_id: str,
        *,
        second_factor_pending: bool = False,
        second_factor_methods: list[str] | None = None,
    ) -> Session:
        now = self._clock()
        session_id = secrets.token_urlsafe(32)
        methods = list(second_factor_methods or [])
        with self._db.transaction() as conn:
            # Opportunistic clean-up: logins are rare enough to pay for it here.
            conn.execute(
                "DELETE FROM sessions WHERE last_seen < ? OR created_at < ?",
                (now - self._idle, now - self._absolute),
            )
            conn.execute(
                "INSERT INTO sessions (id_hash, user_key, user_dn, directory_id, created_at,"
                " last_seen, second_factor_pending, second_factor_methods)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(session_id),
                    dnlib.normalize(user_dn),
                    user_dn,
                    directory_id,
                    now,
                    now,
                    int(second_factor_pending),
                    _dump(methods),
                ),
            )
        session = Session(
            id=session_id,
            user_dn=user_dn,
            directory_id=directory_id,
            created_at=now,
            last_seen=now,
            second_factor_pending=second_factor_pending,
            second_factor_methods=methods,
        )
        session.persisted = _State(second_factor_pending, _dump(methods), 0, {})
        return session

    def get(self, session_id: str) -> Session | None:
        key = _digest(session_id)
        now = self._clock()
        with self._db.connection() as conn:
            seen = conn.execute("SELECT 1 FROM sessions WHERE id_hash = ?", (key,)).fetchone()
        if seen is None:
            # Cookies of long-gone sessions must not cost a write lock.
            self._side_drop(key)
            return None
        with self._db.transaction() as conn:
            row = conn.execute(_SELECT, (key,)).fetchone()
            if row is not None:
                if self._expired(row, now):
                    conn.execute("DELETE FROM sessions WHERE id_hash = ?", (key,))
                    row = None
                else:
                    conn.execute("UPDATE sessions SET last_seen = ? WHERE id_hash = ?", (now, key))
        if row is None:
            self._side_drop(key)
            return None
        return self._loaded(row, session_id, key, now)

    def rotate(self, session_id: str) -> Session | None:
        key = _digest(session_id)
        now = self._clock()
        new_id = secrets.token_urlsafe(32)
        new_key = _digest(new_id)
        with self._db.transaction() as conn:
            row = conn.execute(_SELECT, (key,)).fetchone()
            if row is not None:
                if self._expired(row, now):
                    conn.execute("DELETE FROM sessions WHERE id_hash = ?", (key,))
                    row = None
                else:
                    conn.execute(
                        "UPDATE sessions SET id_hash = ?, last_seen = ? WHERE id_hash = ?",
                        (new_key, now, key),
                    )
        # Process-local values do not follow the session to its new id.
        self._side_drop(key)
        if row is None:
            return None
        return self._loaded(row, new_id, new_key, now)

    def delete(self, session_id: str) -> Session | None:
        key = _digest(session_id)
        with self._db.transaction() as conn:
            row = conn.execute(_SELECT, (key,)).fetchone()
            if row is not None:
                conn.execute("DELETE FROM sessions WHERE id_hash = ?", (key,))
        session = None if row is None else self._loaded(row, session_id, key, row["last_seen"])
        self._side_drop(key)
        return session

    def list_for_user(self, user_dn: str) -> list[SessionInfo]:
        now = self._clock()
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT id_hash, directory_id, created_at, last_seen, cache FROM sessions"
                " WHERE user_key = ? AND second_factor_pending = 0",
                (dnlib.normalize(user_dn),),
            ).fetchall()
        infos: list[SessionInfo] = []
        for row in rows:
            if self._expired(row, now):
                continue
            stored = cast("dict[str, Any]", json.loads(row["cache"]))
            client = cast("dict[str, Any]", _decode(stored.get(CLIENT_KEY, {})))
            infos.append(
                SessionInfo(
                    str(row["id_hash"])[:32],
                    row["directory_id"],
                    float(row["created_at"]),
                    float(row["last_seen"]),
                    str(client.get("ip", "")),
                    str(client.get("ua", "")),
                )
            )
        return sorted(infos, key=lambda i: i.last_seen, reverse=True)

    def delete_for_user(
        self, user_dn: str, *, ref: str | None = None, keep: str | None = None
    ) -> int:
        removed = 0
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id_hash FROM sessions WHERE user_key = ?", (dnlib.normalize(user_dn),)
            ).fetchall()
            for row in rows:
                key = str(row["id_hash"])
                if (ref is not None and key[:32] != ref) or (keep is not None and key[:32] == keep):
                    continue
                conn.execute("DELETE FROM sessions WHERE id_hash = ?", (key,))
                removed += 1
                self._side_drop(key)
        return removed

    def save(self, session: Session) -> None:
        loaded = session.persisted
        if not isinstance(loaded, _State):
            return  # not handed out by this store
        key = _digest(session.id)
        state, local, encoded = self._state_of(key, session)
        if state == loaded:
            return
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT second_factor_pending, second_factor_methods, second_factor_failures,"
                " cache FROM sessions WHERE id_hash = ?",
                (key,),
            ).fetchone()
            if row is None:
                return  # deleted or rotated meanwhile: stays gone
            cache = cast("dict[str, Any]", json.loads(row["cache"]))
            for name, text in state.cache.items():
                if loaded.cache.get(name) != text:
                    cache[name] = encoded[name]
            for name in loaded.cache.keys() - state.cache.keys():
                cache.pop(name, None)
            pending = state.pending if state.pending != loaded.pending else row[0]
            methods = state.methods if state.methods != loaded.methods else row[1]
            failures = int(row[2])
            if state.failures > loaded.failures:
                failures += state.failures - loaded.failures  # count, do not overwrite
            elif state.failures != loaded.failures:
                failures = state.failures
            conn.execute(
                "UPDATE sessions SET second_factor_pending = ?, second_factor_methods = ?,"
                " second_factor_failures = ?, cache = ? WHERE id_hash = ?",
                (int(bool(pending)), methods, failures, _dump(cache), key),
            )
        changed = {
            name: value
            for name, value in local.items()
            if loaded.cache.get(name) != state.cache[name]
        }
        removed = loaded.cache.keys() - state.cache.keys()
        self._side_update(key, changed, removed)
        session.persisted = state
