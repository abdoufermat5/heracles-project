"""Password recovery: token storage, request and confirmation flows.

Tokens are random, stored hashed, valid for a limited time and single use.
The LDAP-backed store (token entries) will be added once the schema constants
are merged; :class:`InMemoryTokenStore` is the interim implementation.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import structlog

from heracles.auth.login import LoginConfig, escape_filter_value, find_user_dn
from heracles.auth.mail import Mailer
from heracles.auth.passwords import PasswordPolicy, is_locked
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Modification, Scope

log = structlog.get_logger(__name__)

TOKEN_TYPE_RECOVERY = "recovery"  # noqa: S105


class RecoveryError(Exception):
    """Token invalid, expired, used, or user unknown (deliberately not distinguished)."""


@dataclass(frozen=True, slots=True)
class TokenRecord:
    user_dn: str
    token_hash: str
    created_at: float
    kind: str = TOKEN_TYPE_RECOVERY


class TokenStore(Protocol):
    def put(self, record: TokenRecord) -> None:
        """Store a token; previous tokens of the same user and kind are replaced."""
        ...

    def consume(self, user_dn: str, token_hash: str, *, kind: str, max_age: float) -> bool:
        """Atomically delete a matching, unexpired token; True if it was valid."""
        ...


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InMemoryTokenStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._records: dict[tuple[str, str], TokenRecord] = {}
        self._lock = threading.Lock()

    def put(self, record: TokenRecord) -> None:
        with self._lock:
            self._records[(dnlib.normalize(record.user_dn), record.kind)] = record

    def consume(self, user_dn: str, token_hash: str, *, kind: str, max_age: float) -> bool:
        key = (dnlib.normalize(user_dn), kind)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return False
            if self._clock() - record.created_at > max_age:
                del self._records[key]
                return False
            if not hmac.compare_digest(record.token_hash, token_hash):
                return False
            del self._records[key]
            return True


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    ttl_seconds: float = 600.0
    #: Absolute URL of the SPA, used to build the link in the mail.
    base_url: str = "http://localhost:8000"
    mail_attribute: str = "mail"
    subject: str = "Password recovery"
    body: str = (
        "Hello,\n\nA password recovery was requested for the account '{login}'.\n"
        "Follow this link within {minutes} minutes to choose a new password:\n\n{link}\n\n"
        "If you did not request it, ignore this message.\n"
    )


class RecoveryService:
    def __init__(
        self,
        *,
        store: TokenStore,
        mailer: Mailer,
        policy: PasswordPolicy,
        login_config: LoginConfig,
        config: RecoveryConfig | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._mailer = mailer
        self._policy = policy
        self._login = login_config
        self._config = config or RecoveryConfig()
        self._clock = clock

    def _find_by_mail(self, directory: DirectoryClient, email: str) -> tuple[str, str] | None:
        """(dn, login) of the single user having this address, else ``None``."""
        attr = self._config.mail_attribute
        flt = (
            f"(&(objectClass={escape_filter_value(self._login.user_object_class)})"
            f"({attr}={escape_filter_value(email)}))"
        )
        found = list(
            directory.search(
                directory.base_dn, flt, Scope.SUBTREE, [self._login.login_attribute], size_limit=0
            )
        )
        if len(found) != 1:
            return None
        login = found[0].text(self._login.login_attribute)
        return (found[0].dn, login) if login else None

    def request(self, directory: DirectoryClient, email: str) -> None:
        """Create a token and mail the link. Never raises for unknown addresses."""
        email = email.strip()
        if not email:
            return
        try:
            match = self._find_by_mail(directory, email)
            if match is None:
                return
            user_dn, login = match
            current = directory.get(user_dn, ["userPassword"])
            current_pw = current.text("userPassword") if current else None
            if current_pw and is_locked(current_pw):
                return
            token = secrets.token_urlsafe(32)
            self._store.put(
                TokenRecord(user_dn, hash_token(token), self._clock(), TOKEN_TYPE_RECOVERY)
            )
            link = (
                f"{self._config.base_url.rstrip('/')}/recovery/confirm"
                f"?login={quote(login, safe='')}&token={quote(token, safe='')}"
            )
            body = self._config.body.format(
                login=login, link=link, minutes=int(self._config.ttl_seconds // 60)
            )
            self._mailer.send(email, self._config.subject, body)
        except (DirectoryError, OSError) as exc:
            log.warning("recovery_request_failed", error=type(exc).__name__)

    def issue(self, directory: DirectoryClient, email: str) -> tuple[str, str] | None:
        """Create a token for the user owning ``email`` and return ``(token, login)``.

        Unlike :meth:`request` nothing is mailed: the caller (a trusted API client) receives
        the token. ``None`` when no single user matches or the account is locked.
        """
        match = self._find_by_mail(directory, email.strip())
        if match is None:
            return None
        user_dn, login = match
        current = directory.get(user_dn, ["userPassword"])
        current_pw = current.text("userPassword") if current else None
        if current_pw and is_locked(current_pw):
            return None
        token = secrets.token_urlsafe(32)
        self._store.put(TokenRecord(user_dn, hash_token(token), self._clock(), TOKEN_TYPE_RECOVERY))
        return token, login

    def confirm(self, directory: DirectoryClient, login: str, token: str, password: str) -> None:
        """Set a new password. Raises :class:`RecoveryError` / :class:`PasswordPolicyError`."""
        user_dn = find_user_dn(directory, self._login, login)
        if user_dn is None or not token:
            raise RecoveryError
        entry = directory.get(user_dn, ["userPassword"])
        current = entry.text("userPassword") if entry else None
        if current and is_locked(current):
            raise RecoveryError
        # Validate the password first so a policy failure does not burn the token.
        self._policy.validate(password)
        if not self._store.consume(
            user_dn,
            hash_token(token),
            kind=TOKEN_TYPE_RECOVERY,
            max_age=self._config.ttl_seconds,
        ):
            raise RecoveryError
        new_value = self._policy.hash_new(password, current_stored=current)
        directory.modify(
            user_dn, [Modification("replace", "userPassword", [new_value.encode("utf-8")])]
        )
