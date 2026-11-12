"""Configuration of the HTTP layer."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from heracles.api.hosts import DEFAULT_ALLOWED_HOSTS
from heracles.auth.oidc import OidcSettings
from heracles.auth.recovery import RecoveryConfig
from heracles.auth.sso import SsoSettings
from heracles.auth.webauthn import WebAuthnSettings


class SessionSettings(BaseModel):
    cookie_name: str = "heracles_session"
    cookie_secure: bool = True
    idle_timeout_seconds: int = 30 * 60
    absolute_timeout_seconds: int = 12 * 3600


class LoginSettings(BaseModel):
    login_attribute: str = "uid"
    user_object_class: str = "inetOrgPerson"
    #: HTTP-header login (trusted reverse proxy). Disabled unless enabled explicitly.
    header_enabled: bool = False
    header_name: str = "AUTH_USER"
    trusted_proxies: list[str] = Field(default_factory=lambda: [])
    #: Rate limiter: free failures before backoff, base and max delay in seconds.
    free_attempts: int = 5
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 900.0
    #: Failed second-factor codes tolerated before the pending session is dropped.
    max_second_factor_failures: int = 5


class RecoverySettings(BaseModel):
    enabled: bool = True
    ttl_minutes: int = 10
    base_url: str = "http://localhost:8000"
    mail_attribute: str = "mail"
    subject: str = "Password recovery"
    body: str = RecoveryConfig().body

    def to_config(self) -> RecoveryConfig:
        return RecoveryConfig(
            ttl_seconds=self.ttl_minutes * 60,
            base_url=self.base_url,
            mail_attribute=self.mail_attribute,
            subject=self.subject,
            body=self.body,
        )


class PasswordSettings(BaseModel):
    min_length: int = 8
    min_differing: int = 0
    default_method: str = "ssha"
    allowed_methods: list[str] = Field(
        default_factory=lambda: [
            "ssha",
            "ssha512",
            "argon2",
            "crypt/sha-512",
            "crypt/sha-256",
            "crypt/blowfish",
        ]
    )
    force_default: bool = False


class BrandingSettings(BaseModel):
    """How the sign-in page and the portal present the organisation."""

    #: Organisation name shown on the sign-in page ("Example Corp").
    organization: str = ""
    #: Logo URL (absolute, or a path under the served frontend); empty for the product mark.
    logo_url: str = ""
    #: One line under the name on the sign-in page.
    tagline: str = ""


class DatabaseSettings(BaseModel):
    """The application's own database (sessions, second factor, task lease, ...)."""

    #: SQLite database file (single node). Unset: in-memory stores (demo, tests); the production
    #: server defaults it to ``$HERACLES_DATA_DIR/heracles.db`` (``/var/lib/heracles``).
    path: Path | None = None
    #: ``postgresql://user:password@host/db``: a PostgreSQL database shared by several replicas
    #: on different hosts (needs the ``postgres`` extra). Takes precedence over ``path``;
    #: ``$HERACLES_DATABASE_URL`` takes precedence over the file.
    url: str | None = None

    @model_validator(mode="after")
    def _env_url(self) -> DatabaseSettings:
        env = os.environ.get("HERACLES_DATABASE_URL", "").strip()
        if env:
            self.url = env
        return self

    @property
    def target(self) -> Path | str | None:
        """What :class:`~heracles.storage.Database` opens: the URL, else the file, else nothing."""
        return self.url or self.path


class PluginsSettings(BaseModel):
    """Which plugins are on (``plugins:`` in the configuration file)."""

    #: Plugin names to enable (``"*"``: all). ``None`` (key absent): the core profile. A plugin is
    #: only registered when the directory schema also defines its objectClasses. Changes
    #: made from the console (stored in the application database) take precedence.
    enabled: list[str] | None = None


class ApiSettings(BaseModel):
    """Everything ``create_app`` needs besides the directories."""

    #: Human labels for the directory selector (id -> label); missing ids use the id.
    directory_labels: dict[str, str] = Field(default_factory=lambda: {})
    #: DNs treated as administrators by the default ``is_admin`` rule.
    admin_dns: list[str] = Field(default_factory=lambda: [])
    session: SessionSettings = Field(default_factory=SessionSettings)
    login: LoginSettings = Field(default_factory=LoginSettings)
    recovery: RecoverySettings = Field(default_factory=RecoverySettings)
    password: PasswordSettings = Field(default_factory=PasswordSettings)
    oidc: OidcSettings = Field(default_factory=OidcSettings)
    webauthn: WebAuthnSettings = Field(default_factory=WebAuthnSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    plugins: PluginsSettings = Field(default_factory=PluginsSettings)
    branding: BrandingSettings = Field(default_factory=BrandingSettings)
    #: Host names the server may build links from when no public address is configured
    #: (``cas_service_name``, the invitations ``public_base_url``): the request ``Host``
    #: header is client-chosen. ``*.example.org`` matches subdomains. Set it in production.
    allowed_hosts: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_HOSTS))
    #: Largest request body accepted by any endpoint, in bytes (413 above, checked while the
    #: body is read, chunked bodies included).
    max_body_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    #: Limit of the import endpoints (``import_paths``): their documents are capped in the
    #: handler (LDIF 10 MiB, CSV 5 MiB) but arrive JSON-escaped.
    max_import_body_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    import_paths: list[str] = Field(
        default_factory=lambda: ["/ldif/import", "/csv/parse", "/csv/import"]
    )
    #: Directory holding the built SPA; served when it exists.
    static_dir: Path | None = None
    enable_docs: bool = False
    #: Issuer name shown in authenticator apps.
    totp_issuer: str = "Heracles"
    # --- P3 compat ---
    #: Login methods (YAML defaults; the directory-stored configuration overrides them).
    sso: SsoSettings = Field(default_factory=SsoSettings)
