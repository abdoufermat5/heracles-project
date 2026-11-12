"""Server-side sessions."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

IDLE_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_TIMEOUT_SECONDS = 12 * 3600


#: Cache key holding where a session was opened from: ``{"ip": ..., "ua": ...}``.
CLIENT_KEY = "client"


def session_ref(session_id: str) -> str:
    """Opaque public reference of a session (never the cookie value itself)."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What the owner (or an administrator) may see of an active session."""

    ref: str
    directory_id: str
    created_at: float
    last_seen: float
    ip: str
    user_agent: str


def client_info(ip: str, user_agent: str | None) -> dict[str, str]:
    """The value of :data:`CLIENT_KEY` for a request."""
    return {"ip": ip[:64], "ua": (user_agent or "")[:300]}


@dataclass(slots=True)
class Session:
    """State attached to one browser session."""

    id: str
    user_dn: str
    directory_id: str
    created_at: float
    last_seen: float
    #: True between a successful first factor and the second factor.
    second_factor_pending: bool = False
    #: Methods the user may use to complete the second factor.
    second_factor_methods: list[str] = field(default_factory=lambda: [])
    #: Failed second-factor attempts in this session.
    second_factor_failures: int = 0
    #: Arbitrary per-session cache (ACL cache, WebAuthn challenge, ...).
    cache: dict[str, Any] = field(default_factory=lambda: {})
    #: Bookkeeping of a persistent store (what was loaded, to save only the changes).
    persisted: Any = field(default=None, repr=False, compare=False)

    @property
    def authenticated(self) -> bool:
        return not self.second_factor_pending


class SessionStore(Protocol):
    """Storage for sessions. Implementations enforce idle/absolute expiry."""

    def create(
        self,
        user_dn: str,
        directory_id: str,
        *,
        second_factor_pending: bool = False,
        second_factor_methods: list[str] | None = None,
    ) -> Session: ...

    def get(self, session_id: str) -> Session | None:
        """Return a live session and refresh ``last_seen``; ``None`` if absent/expired."""
        ...

    def rotate(self, session_id: str) -> Session | None:
        """Give the session a fresh id (old id stops working)."""
        ...

    def delete(self, session_id: str) -> Session | None:
        """Remove the session; return it if it existed."""
        ...

    def save(self, session: Session) -> None:
        """Persist in-place changes made to a session returned by this store.

        A session that was deleted or rotated meanwhile stays gone. Stores that hand out
        the live object (the in-memory one) have nothing to do.
        """
        ...

    def list_for_user(self, user_dn: str) -> list[SessionInfo]:
        """The live, fully authenticated sessions of a user, newest first."""
        ...

    def delete_for_user(
        self, user_dn: str, *, ref: str | None = None, keep: str | None = None
    ) -> int:
        """Revoke the sessions of a user: only ``ref``, or all but ``keep`` (both references).

        Returns how many were removed.
        """
        ...


class InMemorySessionStore:
    """Process-local store, suitable for development and tests."""

    def __init__(
        self,
        *,
        idle_timeout: float = IDLE_TIMEOUT_SECONDS,
        absolute_timeout: float = ABSOLUTE_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._idle = idle_timeout
        self._absolute = absolute_timeout
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    @property
    def idle_timeout(self) -> float:
        """Seconds of inactivity after which a session expires (changeable at runtime)."""
        return self._idle

    @idle_timeout.setter
    def idle_timeout(self, seconds: float) -> None:
        self._idle = seconds

    def _expired(self, s: Session, now: float) -> bool:
        return now - s.last_seen > self._idle or now - s.created_at > self._absolute

    def _purge(self, now: float) -> None:
        for sid in [k for k, v in self._sessions.items() if self._expired(v, now)]:
            del self._sessions[sid]

    def create(
        self,
        user_dn: str,
        directory_id: str,
        *,
        second_factor_pending: bool = False,
        second_factor_methods: list[str] | None = None,
    ) -> Session:
        now = self._clock()
        session = Session(
            id=secrets.token_urlsafe(32),
            user_dn=user_dn,
            directory_id=directory_id,
            created_at=now,
            last_seen=now,
            second_factor_pending=second_factor_pending,
            second_factor_methods=list(second_factor_methods or []),
        )
        with self._lock:
            self._purge(now)
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        now = self._clock()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._expired(session, now):
                del self._sessions[session_id]
                return None
            session.last_seen = now
            return session

    def rotate(self, session_id: str) -> Session | None:
        now = self._clock()
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None or self._expired(session, now):
                return None
            session.id = secrets.token_urlsafe(32)
            session.last_seen = now
            self._sessions[session.id] = session
            return session

    def delete(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.pop(session_id, None)

    def save(self, session: Session) -> None:
        """No-op: callers already hold the live object."""

    def list_for_user(self, user_dn: str) -> list[SessionInfo]:
        now = self._clock()
        wanted = user_dn.lower()
        with self._lock:
            self._purge(now)
            found = [
                s
                for s in self._sessions.values()
                if s.user_dn.lower() == wanted and not s.second_factor_pending
            ]
        infos = [
            SessionInfo(
                session_ref(s.id),
                s.directory_id,
                s.created_at,
                s.last_seen,
                str(s.cache.get(CLIENT_KEY, {}).get("ip", "")),
                str(s.cache.get(CLIENT_KEY, {}).get("ua", "")),
            )
            for s in found
        ]
        return sorted(infos, key=lambda i: i.last_seen, reverse=True)

    def delete_for_user(
        self, user_dn: str, *, ref: str | None = None, keep: str | None = None
    ) -> int:
        wanted = user_dn.lower()
        with self._lock:
            doomed = [
                sid
                for sid, s in self._sessions.items()
                if s.user_dn.lower() == wanted
                and (ref is None or session_ref(sid) == ref)
                and (keep is None or session_ref(sid) != keep)
            ]
            for sid in doomed:
                del self._sessions[sid]
        return len(doomed)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
