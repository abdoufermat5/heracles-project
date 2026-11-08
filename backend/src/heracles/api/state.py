"""Shared application state (services wired by ``create_app``)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from heracles.api.settings import ApiSettings
from heracles.auth.login import IPNetwork, LoginConfig
from heracles.auth.mail import Mailer
from heracles.auth.passwords import PasswordPolicy
from heracles.auth.ratelimit import RateLimiter
from heracles.auth.recovery import RecoveryService
from heracles.auth.second_factor import SecondFactorService
from heracles.auth.sessions import Session, SessionStore
from heracles.auth.webauthn import WebAuthnService
from heracles.ldap.client import DirectoryClient

AdminResolver = Callable[[DirectoryClient, str], bool]
LogoutHook = Callable[[Session], None]


@dataclass(slots=True)
class AppState:
    settings: ApiSettings
    directories: dict[str, DirectoryClient]
    sessions: SessionStore
    limiter: RateLimiter
    second_factor: SecondFactorService
    webauthn: WebAuthnService
    recovery: RecoveryService
    mailer: Mailer
    policy: PasswordPolicy
    login_config: LoginConfig
    trusted_proxies: list[IPNetwork]
    is_admin: AdminResolver
    logout_hooks: list[LogoutHook] = field(default_factory=lambda: [])
    #: Wall clock shared with the session store (injectable in tests).
    clock: Callable[[], float] = time.time
