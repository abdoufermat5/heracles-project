"""Login-method configuration (form, HTTP Basic, trusted header, CAS, OIDC).

The effective configuration is the merge of the YAML settings and the
configuration entry stored in the directory. :func:`effective_sso` reads the
directory-stored values through ``heracles.core.config_store`` when that module
is available and falls back to the YAML settings otherwise.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

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
    """YAML settings overlaid with the directory-stored configuration, when available."""
    base = from_settings(settings)
    if directory is None:
        return base
    try:
        module = importlib.import_module("heracles.core.config_store")
        runtime: Any = module.effective_settings(directory)
    except (ImportError, AttributeError):
        return base
    method = str(getattr(runtime, "login_method", "") or base.login_method)
    if method not in LOGIN_METHODS:
        method = base.login_method
    return SsoConfig(
        login_method=method,
        http_auth_enabled=_as_bool(
            getattr(runtime, "http_auth_enabled", None), base.http_auth_enabled
        ),
        http_header_auth_enabled=_as_bool(
            getattr(runtime, "http_header_auth_enabled", None), base.http_header_auth_enabled
        ),
        http_header_name=str(getattr(runtime, "http_header_name", "") or base.http_header_name),
        cas_enabled=_as_bool(getattr(runtime, "cas_enabled", None), base.cas_enabled),
        cas_host=str(getattr(runtime, "cas_host", "") or base.cas_host),
        cas_port=_as_int(getattr(runtime, "cas_port", None), base.cas_port),
        cas_context=str(getattr(runtime, "cas_context", "") or base.cas_context),
        cas_ca_cert_path=str(getattr(runtime, "cas_ca_cert_path", "") or base.cas_ca_cert_path),
        cas_verbose=_as_bool(getattr(runtime, "cas_verbose", None), base.cas_verbose),
        cas_service_name=str(getattr(runtime, "cas_service_name", "") or base.cas_service_name),
    )
