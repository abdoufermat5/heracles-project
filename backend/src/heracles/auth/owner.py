"""Binding of a session to the directory entry it was opened for.

A session names its user by DN, and a DN can be reused: an account that is deleted, or deleted
and created again for somebody else, must not keep the sessions of its previous holder. The
session records an identity stamp of the entry at login (the server-maintained unique id, see
:data:`~heracles.auth.api_tokens.OWNER_STAMP_ATTRS`, as API tokens do) and the entry is read
again at most every :data:`OWNER_RECHECK_SECONDS`: a session whose entry is gone, replaced or
locked ends. Locks, deletions and password changes also revoke at once
(:func:`heracles.api.accounts.end_account_access`); this check is what makes the end of a
session independent of which writer changed the directory, and of the replica serving it.

The values live in the session cache, so every replica sharing the session store sees them.
"""

from __future__ import annotations

from collections.abc import Callable

from heracles.auth.api_tokens import OWNER_STAMP_ATTRS, owner_stamp
from heracles.auth.passwords.lock import is_locked
from heracles.auth.sessions import Session
from heracles.ldap.client import DirectoryClient, Entry
from heracles.schema.names import STD_ATTR

#: Session cache keys: the identity stamp of the entry (``""`` if the directory gives none),
#: and when it was last compared with the directory.
OWNER_STAMP_KEY = "owner.stamp"
OWNER_CHECKED_KEY = "owner.checked"

#: Longest a session outlives the deletion, replacement or lock of its entry.
OWNER_RECHECK_SECONDS = 30.0

_ATTRS = [STD_ATTR.USER_PASSWORD, *OWNER_STAMP_ATTRS]


def _read(directory: DirectoryClient, dn: str) -> Entry | None:
    return directory.get(dn, _ATTRS)


def bind_owner(session: Session, directory: DirectoryClient, now: float) -> None:
    """Record the identity of the session's entry (call right after the login)."""
    entry = _read(directory, session.user_dn)
    session.cache[OWNER_STAMP_KEY] = owner_stamp(entry.text) if entry is not None else ""
    session.cache[OWNER_CHECKED_KEY] = now


def owner_is_current(
    session: Session,
    directory: DirectoryClient,
    now: float,
    *,
    is_admin: Callable[[DirectoryClient, str], bool],
) -> bool:
    """Whether the entry the session was opened for still exists, unchanged and unlocked.

    Compares with the directory at most every :data:`OWNER_RECHECK_SECONDS`. A bootstrap
    administrator without an entry of their own stays valid. A session that predates the
    stamp is bound to whatever the entry is now.
    """
    checked = session.cache.get(OWNER_CHECKED_KEY)
    if (
        isinstance(checked, int | float)
        and OWNER_STAMP_KEY in session.cache
        and 0 <= now - checked < OWNER_RECHECK_SECONDS
    ):
        return True
    entry = _read(directory, session.user_dn)
    if entry is None:
        return is_admin(directory, session.user_dn)
    stamp = owner_stamp(entry.text)
    recorded = session.cache.get(OWNER_STAMP_KEY)
    if isinstance(recorded, str) and recorded and stamp != recorded:
        return False
    stored = entry.text(STD_ATTR.USER_PASSWORD) or ""
    if stored and is_locked(stored):
        return False
    session.cache[OWNER_STAMP_KEY] = stamp
    session.cache[OWNER_CHECKED_KEY] = now
    return True
