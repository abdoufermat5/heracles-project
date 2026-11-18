"""Which ``Host`` values may be used to build links when no public address is configured."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from heracles.api.hosts import DEFAULT_ALLOWED_HOSTS, host_allowed, request_base
from heracles.auth.login import parse_networks


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("LOCALHOST:8000", True),
        ("127.0.0.1:5173", True),
        ("[::1]:8000", True),
        ("testserver", True),
        ("evil.example", False),
        ("localhost.evil.example", False),
        ("evil.example/localhost", False),
        ("localhost:notaport", False),
        ("localhost@evil.example", False),
        ("evil.example\\@localhost", False),
        ("", False),
    ],
)
def test_default_hosts(host: str, expected: bool) -> None:
    assert host_allowed(host, list(DEFAULT_ALLOWED_HOSTS)) is expected


def test_wildcard_matches_subdomains_only() -> None:
    allowed = ["*.example.org", "console.corp.test"]
    assert host_allowed("a.example.org", allowed)
    assert host_allowed("a.b.example.org:8443", allowed)
    assert not host_allowed("example.org", allowed)
    assert not host_allowed("badexample.org", allowed)
    assert host_allowed("Console.Corp.Test.", allowed)
    assert not host_allowed("localhost", allowed)


@pytest.mark.parametrize(
    ("peer", "expected"),
    [
        ("10.0.0.5", "https://app.example"),  # the TLS ingress is trusted
        ("203.0.113.9", "http://app.example"),  # anyone else cannot choose the scheme
    ],
)
def test_request_base_honours_forwarded_proto_only_from_trusted_proxies(
    peer: str, expected: str
) -> None:
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("heracles", 8000),
            "client": (peer, 1234),
            "path": "/",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"app.example"), (b"x-forwarded-proto", b"https")],
        }
    )
    base = request_base(
        request, ["app.example"], setting="x", trusted_proxies=parse_networks(["10.0.0.0/8"])
    )
    assert base == expected
