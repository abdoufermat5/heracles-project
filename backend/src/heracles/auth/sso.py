"""Login-method configuration (form, HTTP Basic, trusted header, CAS, OIDC).

The effective configuration is the merge of the YAML settings and the
configuration entry stored in the directory. :func:`effective_sso` reads the
directory-stored values through ``heracles.core.config_store`` when that module
is available and falls back to the YAML settings otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from heracles.core.config_store import effective_settings
from heracles.ldap.client import DirectoryClient

LoginMethod = Literal["form", "http-basic", "http-header", "cas", "oidc"]
LOGIN_METHODS: tuple[str, ...] = ("form", "http-basic", "http-header", "cas", "oidc")


class SsoSettings(BaseModel):
    """YAML defaults of the login methods (``api.sso``)."""

    login_method: str = "form"
    http_auth_enabled: bool = False
    http_header_auth_enabled: bool = False
    http_header_name: str = "AUTH_USER"
    cas_enabled: bool = False
    cas_host: str = ""
    cas_port: int = 443
    cas_context: str = "/cas"
    cas_ca_cert_path: str = ""
    cas_verbose: bool = False
    #: Public URL (or host name) of this application as seen by the CAS server.
    cas_service_name: str = ""


@dataclass(frozen=True, slots=True)
class SsoConfig:
    """Effective login-method configuration."""

    login_method: str = "form"
    http_auth_enabled: bool = False
    http_header_auth_enabled: bool = False
    http_header_name: str = "AUTH_USER"
    cas_enabled: bool = False
    cas_host: str = ""
    cas_port: int = 443
    cas_context: str = "/cas"
    cas_ca_cert_path: str = ""
    cas_verbose: bool = False
    cas_service_name: str = ""

    @property
    def cas_available(self) -> bool:
        """CAS can be used: activated (or selected as login method) and a host is known."""
        return bool(self.cas_host) and (self.cas_enabled or self.login_method == "cas")

    @property
    def basic_available(self) -> bool:
        return self.http_auth_enabled or self.login_method == "http-basic"


def from_settings(settings: SsoSettings) -> SsoConfig:
    """The YAML configuration."""
    return SsoConfig(**settings.model_dump())


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().upper() in ("TRUE", "1", "YES", "ON")
    return bool(value)


def _as_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def effective_sso(settings: SsoSettings, directory: DirectoryClient | None) -> SsoConfig:
    """YAML settings overlaid with the directory-stored configuration.

    Only the knobs the configuration entry actually stores override the YAML
    defaults (``RuntimeConfig.from_directory``), so an installation that has not
    created the entry keeps its file configuration.
    """
    base = from_settings(settings)
    if directory is None:
        return base
    try:
        runtime = effective_settings(directory)
    except Exception:  # a broken configuration entry must not block login
        return base
    stored = runtime.from_directory

    def text(key: str, default: str) -> str:
        return str(getattr(runtime, key, "") or default) if key in stored else default

    def flag(key: str, default: bool) -> bool:
        return _as_bool(getattr(runtime, key, None), default) if key in stored else default

    method = text("login_method", base.login_method)
    if method not in LOGIN_METHODS:
        method = base.login_method
    return SsoConfig(
        login_method=method,
        http_auth_enabled=flag("http_auth_enabled", base.http_auth_enabled),
        http_header_auth_enabled=flag("http_header_auth_enabled", base.http_header_auth_enabled),
        http_header_name=text("http_header_name", base.http_header_name),
        cas_enabled=flag("cas_enabled", base.cas_enabled),
        cas_host=text("cas_host", base.cas_host),
        cas_port=(
            _as_int(getattr(runtime, "cas_port", None), base.cas_port)
            if "cas_port" in stored
            else base.cas_port
        ),
        cas_context=text("cas_context", base.cas_context),
        cas_ca_cert_path=text("cas_ca_cert_path", base.cas_ca_cert_path),
        cas_verbose=flag("cas_verbose", base.cas_verbose),
        cas_service_name=text("cas_service_name", base.cas_service_name),
    )
