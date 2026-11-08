"""CAS client: URLs, ticket validation (fake CAS server through a mock transport)."""

from __future__ import annotations

import httpx2
import pytest

from heracles import demo
from heracles.auth.cas import CasClient, CasError, parse_validation
from heracles.auth.sso import SsoConfig, SsoSettings, effective_sso
from heracles.core import config_store

SERVICE = "https://heracles.example.org/api/v2/auth/cas/callback?directory=main"
CONFIG = SsoConfig(login_method="cas", cas_enabled=True, cas_host="cas.example.org", cas_port=8443)

SUCCESS = """<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
  <cas:authenticationSuccess>
    <cas:user>jdoe</cas:user>
    <cas:attributes><cas:mail>jdoe@example.org</cas:mail><cas:mail>j@example.org</cas:mail></cas:attributes>
  </cas:authenticationSuccess>
</cas:serviceResponse>"""
FAILURE = """<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
  <cas:authenticationFailure code="INVALID_TICKET">Ticket not recognized</cas:authenticationFailure>
</cas:serviceResponse>"""


def client_for(handler: httpx2.MockTransport) -> CasClient:
    return CasClient(CONFIG, transport=handler)


def test_urls() -> None:
    cas = CasClient(CONFIG)
    assert cas.base_url == "https://cas.example.org:8443/cas"
    assert cas.login_url(SERVICE).startswith(
        "https://cas.example.org:8443/cas/login?service=https%3A"
    )
    assert "/logout?service=" in cas.logout_url(SERVICE)
    assert "ticket=ST-1" in cas.validate_url("ST-1", SERVICE)
    bare = CasClient(SsoConfig(cas_host="h", cas_port=443, cas_context="/"))
    assert bare.base_url == "https://h:443"


def test_validate_success_with_attributes() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text=SUCCESS)

    user = client_for(httpx2.MockTransport(handler)).validate("ST-1", SERVICE)
    assert user.name == "jdoe"
    assert user.attributes["mail"] == ["jdoe@example.org", "j@example.org"]
    assert seen[0].url.path == "/cas/serviceValidate"
    assert seen[0].url.params["ticket"] == "ST-1"
    assert seen[0].url.params["service"] == SERVICE


def test_validate_failures() -> None:
    cases = [
        httpx2.Response(200, text=FAILURE),
        httpx2.Response(200, text="not xml"),
        httpx2.Response(200, text="<other/>"),
        httpx2.Response(500, text="boom"),
    ]
    for response in cases:
        transport = httpx2.MockTransport(lambda _r, resp=response: resp)  # type: ignore[misc]
        with pytest.raises(CasError):
            client_for(transport).validate("ST-1", SERVICE)
    with pytest.raises(CasError):
        client_for(httpx2.MockTransport(lambda _r: httpx2.Response(200))).validate("", SERVICE)


def test_validate_unreachable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(CasError, match="unreachable"):
        client_for(httpx2.MockTransport(handler)).validate("ST-1", SERVICE)


def test_parse_rejects_empty_user() -> None:
    body = SUCCESS.replace("<cas:user>jdoe</cas:user>", "<cas:user> </cas:user>")
    with pytest.raises(CasError):
        parse_validation(body)


def test_effective_sso_falls_back_to_yaml() -> None:
    cfg = effective_sso(SsoSettings(login_method="cas", cas_host="x"), None)
    assert cfg.login_method == "cas" and cfg.cas_available
    assert not SsoConfig(cas_host="x").cas_available  # not activated


def test_effective_sso_reads_the_stored_configuration() -> None:
    directory = demo.build_demo_directory()
    config_store.save_config(
        directory,
        {
            "login_method": "cas",
            "http_auth_enabled": True,
            "http_header_name": "X-User",
            "cas_host": "cas.stored",
            "cas_port": 9443,
            "cas_ca_cert_path": "/ca.pem",
            "cas_service_name": "heracles.stored",
        },
    )
    config_store.invalidate(directory)
    settings = SsoSettings(login_method="form", cas_context="/cas")
    cfg = effective_sso(settings, directory)
    assert cfg.login_method == "cas" and cfg.http_auth_enabled is True
    assert cfg.cas_host == "cas.stored" and cfg.cas_port == 9443
    assert cfg.cas_context == "/cas"  # not stored: the YAML value stays
    assert cfg.http_header_name == "X-User" and cfg.cas_ca_cert_path == "/ca.pem"


def test_effective_sso_keeps_yaml_when_the_entry_stores_nothing() -> None:
    directory = demo.build_demo_directory()
    settings = SsoSettings(login_method="cas", cas_host="yaml.example.org")
    cfg = effective_sso(settings, directory)
    assert cfg.login_method == "cas" and cfg.cas_host == "yaml.example.org"
