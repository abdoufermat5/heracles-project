"""Which ``Host`` values may be used to build links when no public address is configured."""

from __future__ import annotations

import pytest

from heracles.api.hosts import DEFAULT_ALLOWED_HOSTS, host_allowed


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
