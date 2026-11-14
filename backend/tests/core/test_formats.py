import pytest

from heracles.core.formats import check


@pytest.mark.parametrize(
    ("fmt", "value"),
    [
        ("dn", "ou=people,dc=example,dc=com"),
        ("dn", r"cn=Doe\, John,dc=example,dc=com"),
        ("rdn", "ou=people"),
        ("abs_path", "/bin/bash"),
        ("hostname", "cas.example.com"),
        ("domain", "example.com"),
        ("port", "389"),
        ("attribute", "uid"),
        ("attribute", "2.5.4.3"),
        ("ldap_filter", "(&(objectClass=person)(uid=*))"),
        ("timezone", "Europe/Paris"),
    ],
)
def test_valid_values_pass(fmt: str, value: str) -> None:
    assert check(fmt, value) is None


@pytest.mark.parametrize(
    ("fmt", "value"),
    [
        ("dn", "anything"),
        ("dn", "ou=,dc=example"),
        ("rdn", "ou=a,ou=b"),
        ("dn", "dc=a,,dc=b"),
        ("dn", "dc=a,"),
        ("dn", ",dc=a"),
        ("ldap_filter", "uid=x"),
        ("rdn", "people"),
        ("abs_path", "bash"),
        ("abs_path", "/usr/bin/"),
        ("hostname", "has space"),
        ("domain", "localhost"),
        ("port", "0"),
        ("port", "65536"),
        ("attribute", "u id"),
        ("ldap_filter", "(uid="),
        ("timezone", "Mars/Olympus"),
    ],
)
def test_invalid_values_refused(fmt: str, value: str) -> None:
    assert check(fmt, value) is not None


def test_empty_passes_every_format() -> None:
    for fmt in ("dn", "rdn", "abs_path", "hostname", "domain", "port", "attribute", "ldap_filter"):
        assert check(fmt, "") is None
