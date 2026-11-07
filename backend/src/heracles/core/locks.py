"""Edit locks stored in the directory (compatibility entry format below).

* entry DN: ``cn=<md5hex(object dn)>,<locks container>``;
* user DN stored plain, object DN stored base64 (searchable by equality);
* timestamp is a GeneralizedTime in UTC.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from heracles.core.containers import ensure_container
from heracles.core.generalized_time import format_generalized_time, parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles.schema import legacy

_A = legacy.ATTR


@dataclass(frozen=True, slots=True)
class Lock:
    """An edit lock held by ``user_dn`` on ``object_dn``."""

    entry_dn: str
    object_dn: str
    user_dn: str
    acquired_at: datetime


class LockedError(Exception):
    """The object is already locked by another user."""

    def __init__(self, lock: Lock) -> None:
        super().__init__(f"{lock.object_dn} is locked by {lock.user_dn}")
        self.lock = lock


def encode_object_dn(object_dn: str) -> str:
    """Base64 form of ``object_dn`` as stored in the lock entry."""
    return base64.b64encode(object_dn.encode("utf-8")).decode("ascii")


def lock_cn(object_dn: str) -> str:
    """RDN value of the lock entry for ``object_dn``."""
    return hashlib.md5(object_dn.encode("utf-8"), usedforsecurity=False).hexdigest()


class LockService:
    """Acquire, inspect and release edit locks."""

    def __init__(
        self,
        directory: DirectoryClient,
        *,
        locks_base: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._dir = directory
        self.locks_base = locks_base or dnlib.join(legacy.RDN.LOCKS, directory.base_dn)
        self._clock = clock or (lambda: datetime.now(UTC))

    def acquire(self, object_dn: str, user_dn: str) -> Lock:
        """Lock ``object_dn`` for ``user_dn``.

        Re-locking an object already held by the same user is a no-op.

        Raises:
            LockedError: held by another user.
        """
        existing = self.get(object_dn)
        if existing is not None:
            return self._claim(existing, user_dn)
        ensure_container(self._dir, self.locks_base)
        entry_dn = f"cn={lock_cn(object_dn)},{self.locks_base}"
        now = self._clock()
        try:
            self._dir.add(
                entry_dn,
                {
                    "objectClass": [legacy.OC.LOCK.encode()],
                    "cn": [lock_cn(object_dn).encode()],
                    _A.LOCK_USER_DN: [user_dn.encode("utf-8")],
                    _A.LOCK_OBJECT_DN: [encode_object_dn(object_dn).encode()],
                    _A.LOCK_TIMESTAMP: [format_generalized_time(now).encode()],
                },
            )
        except AlreadyExistsError:
            raced = self.get(object_dn)
            if raced is None:
                raise
            return self._claim(raced, user_dn)
        return Lock(entry_dn, object_dn, user_dn, now.replace(microsecond=0))

    @staticmethod
    def _claim(lock: Lock, user_dn: str) -> Lock:
        if dnlib.normalize(lock.user_dn) != dnlib.normalize(user_dn):
            raise LockedError(lock)
        return lock

    def get(self, object_dn: str) -> Lock | None:
        """Return the lock on ``object_dn`` if any."""
        flt = (
            f"(&(objectClass={legacy.OC.LOCK})"
            f"({_A.LOCK_OBJECT_DN}={escape_filter_value(encode_object_dn(object_dn))}))"
        )
        try:
            for entry in self._dir.search(self.locks_base, flt, Scope.ONE):
                lock = self._to_lock(entry)
                if lock is not None and lock.object_dn == object_dn:
                    return lock
        except NoSuchObjectError:
            return None
        return None

    def list_by_user(self, user_dn: str) -> list[Lock]:
        """All locks held by ``user_dn``."""
        flt = f"(&(objectClass={legacy.OC.LOCK})({_A.LOCK_USER_DN}={escape_filter_value(user_dn)}))"
        return self._search(flt)

    def list_all(self) -> list[Lock]:
        """All locks in the directory."""
        return self._search(f"(objectClass={legacy.OC.LOCK})")

    def release(self, object_dn: str, user_dn: str) -> bool:
        """Release the lock on ``object_dn`` if held by ``user_dn``.

        Returns ``True`` when a lock was removed. A lock held by someone else
        is left untouched (use :meth:`break_lock`).
        """
        lock = self.get(object_dn)
        if lock is None or dnlib.normalize(lock.user_dn) != dnlib.normalize(user_dn):
            return False
        return self._remove(lock)

    def break_lock(self, object_dn: str) -> bool:
        """Remove the lock on ``object_dn`` whoever holds it."""
        lock = self.get(object_dn)
        return self._remove(lock) if lock is not None else False

    def release_all_for_user(self, user_dn: str) -> int:
        """Remove every lock held by ``user_dn``; returns how many."""
        return sum(1 for lock in self.list_by_user(user_dn) if self._remove(lock))

    def _remove(self, lock: Lock) -> bool:
        try:
            self._dir.delete(lock.entry_dn)
        except NoSuchObjectError:
            return False
        return True

    def _search(self, flt: str) -> list[Lock]:
        try:
            entries = list(self._dir.search(self.locks_base, flt, Scope.ONE))
        except NoSuchObjectError:
            return []
        locks = [lock for e in entries if (lock := self._to_lock(e)) is not None]
        return sorted(locks, key=lambda lk: (lk.acquired_at, lk.object_dn))

    @staticmethod
    def _to_lock(entry: Entry) -> Lock | None:
        raw_obj = entry.text(_A.LOCK_OBJECT_DN)
        user = entry.text(_A.LOCK_USER_DN)
        stamp = entry.text(_A.LOCK_TIMESTAMP)
        if raw_obj is None or user is None or stamp is None:
            return None
        try:
            object_dn = base64.b64decode(raw_obj, validate=True).decode("utf-8")
            acquired = parse_generalized_time(stamp)
        except ValueError:
            return None
        return Lock(entry.dn, object_dn, user, acquired)
