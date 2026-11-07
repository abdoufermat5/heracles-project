"""Server-side sessions."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

IDLE_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_TIMEOUT_SECONDS = 12 * 3600


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

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
