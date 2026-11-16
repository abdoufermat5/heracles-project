"""API tokens: long-lived, scoped, revocable credentials for scripts and automation.

A token belongs to one person of one directory (its *owner*) and acts as that person: the
ACL of the owner applies to every request, and the token's scopes can only narrow it.
The secret is shown once, at creation; the store keeps its SHA-256 only.

Wire format: ``hrc_<id>_<secret>``, sent as ``Authorization: Bearer <token>``. ``<id>`` is
16 hex characters (public, it names the token in lists and audit events); ``<secret>`` is
43 URL-safe characters (256 bits).

Scopes are levels: ``read`` (safe methods on the object and type endpoints), ``write``
(``read`` plus changes to objects) and ``admin`` (``write`` plus the administration
endpoints: configuration, hooks, plugins, ACL roles, imports). A token may also be limited
to some object types. :mod:`heracles.api.tokens` maps the routes to the scopes.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Final, Protocol

from heracles.ldap import dn as dnlib

PREFIX: Final = "hrc_"
_ID_HEX: Final = 16
_TOKEN_RE: Final = re.compile(r"^hrc_([0-9a-f]{16})_([A-Za-z0-9_-]{43})$")

READ: Final = "read"
WRITE: Final = "write"
ADMIN: Final = "admin"
#: The scope levels, weakest first: each one includes the previous ones.
SCOPES: Final = (READ, WRITE, ADMIN)

#: Session cache key marking the throw-away session of a token request (value: token id).
SESSION_KEY: Final = "api_token"

#: ``last_used`` is written at most this often per token (a request is not a database write).
TOUCH_INTERVAL_SECONDS: Final = 60.0


@dataclass(frozen=True, slots=True)
class ApiToken:
    id: str
    owner_dn: str
    directory_id: str
    name: str
    #: The scope level (one of :data:`SCOPES`).
    scope: str
    #: Object types the token is limited to; empty: every type.
    types: tuple[str, ...]
    created_at: float
    expires_at: float
    #: DN of the person who created it (the owner, today).
    created_by: str
    secret_hash: str
    last_used_at: float | None = None
    last_used_ip: str = ""
    #: Networks (CIDR) the token may be used from; empty: any address.
    allowed_ips: tuple[str, ...] = ()

    def allows(self, scope: str) -> bool:
        """Whether the token's level includes ``scope``."""
        return SCOPES.index(self.scope) >= SCOPES.index(scope)

    def allows_ip(self, ip: str) -> bool:
        """Whether a request from ``ip`` may use the token (an unreadable address may not)."""
        if not self.allowed_ips:
            return True
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(address in ipaddress.ip_network(net) for net in self.allowed_ips)


#: Most networks one token may list.
MAX_ALLOWED_IPS: Final = 32


def normalize_networks(values: Iterable[str]) -> tuple[str, ...]:
    """Networks in their canonical CIDR form (an address alone is a /32 or /128).

    Raises ``ValueError`` naming the first value that is not an address or a network.
    """
    out: list[str] = []
    for raw in values:
        text = raw.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            raise ValueError(text) from None
        if str(network) not in out:
            out.append(str(network))
    if len(out) > MAX_ALLOWED_IPS:
        raise ValueError(f"more than {MAX_ALLOWED_IPS} networks")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class NewToken:
    """A created token and its secret (the only time the secret is known)."""

    token: ApiToken
    secret: str


def token_session_id(token_id: str) -> str:
    """Id of the throw-away session a token request runs in (also keys its listing snapshots)."""
    return f"{SESSION_KEY}:{token_id}"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse(raw: str) -> tuple[str, str] | None:
    """``(id, secret)`` of a token string, or ``None`` when it is not shaped like one."""
    m = _TOKEN_RE.match(raw.strip())
    return (m.group(1), m.group(2)) if m else None


def token_id_of(raw: str) -> str | None:
    """The public id of a token string (no lookup), or ``None``."""
    parsed = parse(raw)
    return parsed[0] if parsed else None


def generate(
    *,
    owner_dn: str,
    directory_id: str,
    name: str,
    scope: str,
    types: Iterable[str],
    expires_at: float,
    created_by: str,
    now: float,
    allowed_ips: Iterable[str] = (),
) -> NewToken:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    token_id = secrets.token_hex(_ID_HEX // 2)
    secret = secrets.token_urlsafe(32)
    token = ApiToken(
        id=token_id,
        owner_dn=owner_dn,
        directory_id=directory_id,
        name=name,
        scope=scope,
        types=tuple(sorted(set(types))),
        created_at=now,
        expires_at=expires_at,
        created_by=created_by,
        secret_hash=hash_secret(secret),
        allowed_ips=normalize_networks(allowed_ips),
    )
    return NewToken(token, f"{PREFIX}{token_id}_{secret}")


def verify(token: ApiToken, secret: str) -> bool:
    return hmac.compare_digest(token.secret_hash, hash_secret(secret))


class ApiTokenStore(Protocol):
    """Where tokens live (the application database, or memory in tests and the demo)."""

    def add(self, token: ApiToken) -> None: ...

    def get(self, token_id: str) -> ApiToken | None: ...

    def list_for_owner(self, owner_dn: str) -> list[ApiToken]: ...

    def list_all(self) -> list[ApiToken]: ...

    def delete(self, token_id: str) -> bool: ...

    def delete_for_owner(self, owner_dn: str) -> int:
        """Remove every token of a person; returns how many there were."""
        ...

    def touch(self, token_id: str, at: float, ip: str) -> None:
        """Record a use (callers throttle with :data:`TOUCH_INTERVAL_SECONDS`)."""
        ...

    def purge_expired(self, now: float) -> int: ...


class InMemoryApiTokenStore:
    """:class:`ApiTokenStore` in a dict (single process)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._tokens: dict[str, ApiToken] = {}
        self._lock = threading.Lock()

    def add(self, token: ApiToken) -> None:
        with self._lock:
            self._tokens[token.id] = token

    def get(self, token_id: str) -> ApiToken | None:
        return self._tokens.get(token_id)

    def list_for_owner(self, owner_dn: str) -> list[ApiToken]:
        key = dnlib.normalize(owner_dn)
        found = [t for t in self._tokens.values() if dnlib.normalize(t.owner_dn) == key]
        return sorted(found, key=lambda t: t.created_at)

    def list_all(self) -> list[ApiToken]:
        return sorted(self._tokens.values(), key=lambda t: t.created_at)

    def delete(self, token_id: str) -> bool:
        with self._lock:
            return self._tokens.pop(token_id, None) is not None

    def delete_for_owner(self, owner_dn: str) -> int:
        key = dnlib.normalize(owner_dn)
        with self._lock:
            gone = [i for i, t in self._tokens.items() if dnlib.normalize(t.owner_dn) == key]
            for i in gone:
                del self._tokens[i]
        return len(gone)

    def touch(self, token_id: str, at: float, ip: str) -> None:
        with self._lock:
            token = self._tokens.get(token_id)
            if token is not None:
                self._tokens[token_id] = replace(token, last_used_at=at, last_used_ip=ip[:64])

    def purge_expired(self, now: float) -> int:
        with self._lock:
            gone = [i for i, t in self._tokens.items() if t.expires_at <= now]
            for i in gone:
                del self._tokens[i]
        return len(gone)


__all__ = [
    "ADMIN",
    "PREFIX",
    "READ",
    "SCOPES",
    "SESSION_KEY",
    "TOUCH_INTERVAL_SECONDS",
    "WRITE",
    "ApiToken",
    "ApiTokenStore",
    "InMemoryApiTokenStore",
    "NewToken",
    "generate",
    "hash_secret",
    "parse",
    "token_id_of",
    "token_session_id",
    "verify",
]
