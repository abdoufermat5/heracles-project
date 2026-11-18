"""Login-method configuration (form, HTTP Basic, trusted header, CAS).

The configuration comes from the YAML settings only (:func:`effective_sso`), like
OpenID Connect: the directory-stored configuration entry never changes how people
sign in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

LoginMethod = Literal["form", "http-basic", "http-header", "cas"]
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


def effective_sso(settings: SsoSettings) -> SsoConfig:
    """The login-method configuration: the YAML settings only.

    The directory-stored configuration entry may hold the same keys (they round-trip
    for compatibility), but they are never read here: whoever may edit that entry must
    not be able to point sign-in at another CAS server or have a forged header trusted.
    """
    return SsoConfig(**settings.model_dump())
