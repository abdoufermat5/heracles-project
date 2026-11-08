"""CAS (protocol v2 / v3) client: login redirect, ticket validation, logout redirect."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx2
import structlog

from heracles.auth.sso import SsoConfig

log = structlog.get_logger(__name__)

CAS_NS = "{http://www.yale.edu/tp/cas}"
VALIDATE_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 256 * 1024


class CasError(Exception):
    """Ticket validation failed (invalid ticket, unreachable server, malformed answer)."""


@dataclass(frozen=True, slots=True)
class CasUser:
    """A validated CAS principal."""

    name: str
    attributes: dict[str, list[str]] = field(default_factory=lambda: {})


class CasClient:
    """Talks to one CAS server described by an :class:`SsoConfig`."""

    def __init__(self, config: SsoConfig, *, transport: httpx2.BaseTransport | None = None) -> None:
        self._config = config
        self._transport = transport

    @property
    def base_url(self) -> str:
        cfg = self._config
        context = "/" + cfg.cas_context.strip("/") if cfg.cas_context.strip("/") else ""
        return f"https://{cfg.cas_host}:{cfg.cas_port}{context}"

    def login_url(self, service: str) -> str:
        return f"{self.base_url}/login?{urlencode({'service': service})}"

    def logout_url(self, service: str) -> str:
        return f"{self.base_url}/logout?{urlencode({'service': service})}"

    def validate_url(self, ticket: str, service: str) -> str:
        return (
            f"{self.base_url}/serviceValidate?{urlencode({'service': service, 'ticket': ticket})}"
        )

    def _http(self) -> httpx2.Client:
        ca = self._config.cas_ca_cert_path
        verify: str | bool = ca if ca else True
        if self._transport is not None:
            return httpx2.Client(transport=self._transport, timeout=VALIDATE_TIMEOUT_SECONDS)
        return httpx2.Client(
            verify=verify, timeout=VALIDATE_TIMEOUT_SECONDS, follow_redirects=False
        )

    def validate(self, ticket: str, service: str) -> CasUser:
        """Validate ``ticket`` for ``service`` with ``serviceValidate``; raise :class:`CasError`."""
        if not ticket or len(ticket) > 512:
            raise CasError("invalid ticket")
        try:
            with self._http() as http:
                response = http.get(self.validate_url(ticket, service))
        except httpx2.HTTPError as exc:
            log.warning("cas_unreachable", error=type(exc).__name__)
            raise CasError("CAS server unreachable") from exc
        if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
            raise CasError("unexpected CAS answer")
        return parse_validation(response.text)


def parse_validation(body: str) -> CasUser:
    """Parse a ``serviceValidateResponse`` document."""
    try:
        root = ElementTree.fromstring(body)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise CasError("malformed CAS answer") from exc
    if root.tag != f"{CAS_NS}serviceResponse":
        raise CasError("malformed CAS answer")
    failure = root.find(f"{CAS_NS}authenticationFailure")
    if failure is not None:
        raise CasError(failure.get("code", "authentication failure"))
    success = root.find(f"{CAS_NS}authenticationSuccess")
    if success is None:
        raise CasError("malformed CAS answer")
    user = success.findtext(f"{CAS_NS}user", default="").strip()
    if not user:
        raise CasError("no user in CAS answer")
    attributes: dict[str, list[str]] = {}
    container = success.find(f"{CAS_NS}attributes")
    if container is not None:
        for child in container:
            name = child.tag.removeprefix(CAS_NS)
            attributes.setdefault(name, []).append((child.text or "").strip())
    return CasUser(user, attributes)
