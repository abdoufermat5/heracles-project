"""First-factor login methods: LDAP bind and trusted HTTP header."""

from __future__ import annotations

import contextlib
import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

from heracles.ldap.client import DirectoryClient, DirectoryError, Scope

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class InvalidLoginError(Exception):
    """Unknown user, ambiguous match or wrong password (deliberately not distinguished)."""


@dataclass(frozen=True, slots=True)
class LoginConfig:
    """How to find a user from what was typed in the login form."""

    login_attribute: str = "uid"
    user_object_class: str = "inetOrgPerson"


def escape_filter_value(value: str) -> str:
    """Escape a value for use inside an LDAP filter (RFC 4515)."""
    out: list[str] = []
    for byte in value.encode("utf-8"):
        if byte in (0x2A, 0x28, 0x29, 0x5C, 0x00) or byte >= 0x80:
            out.append(f"\\{byte:02x}")
        else:
            out.append(chr(byte))
    return "".join(out)


def user_filter(config: LoginConfig, login: str) -> str:
    return (
        f"(&(objectClass={escape_filter_value(config.user_object_class)})"
        f"({config.login_attribute}={escape_filter_value(login)}))"
    )


def find_user_dn(directory: DirectoryClient, config: LoginConfig, login: str) -> str | None:
    """DN of the single user matching ``login``; ``None`` for zero or several matches."""
    if not login.strip():
        return None
    matches: list[str] = []
    for entry in directory.search(
        directory.base_dn,
        user_filter(config, login),
        Scope.SUBTREE,
        [config.login_attribute],
    ):
        matches.append(entry.dn)
        if len(matches) > 1:
            return None
    return matches[0] if matches else None


#: RDN of the DN that an unknown login is bound against. A login that matches no user must
#: cost a bind too, or the response time tells an attacker whether the account exists.
_UNKNOWN_LOGIN_RDN = "uid=heracles-unknown-login"


def _bind_unknown_login(directory: DirectoryClient, password: str) -> None:
    """Do the work of a bind for a login that matched no user; the result is ignored."""
    with contextlib.suppress(DirectoryError):
        directory.check_password(f"{_UNKNOWN_LOGIN_RDN},{directory.base_dn}", password)


def authenticate_bind(
    directory: DirectoryClient, config: LoginConfig, login: str, password: str
) -> str:
    """Look the user up and bind with ``password``; return the user DN.

    An empty password is always refused (it would turn into an anonymous bind). An unknown
    login is bound against a fixed dummy DN, so both outcomes cost the same.
    """
    if not password:
        raise InvalidLoginError
    dn = find_user_dn(directory, config, login)
    if dn is None:
        _bind_unknown_login(directory, password)
        raise InvalidLoginError
    try:
        ok = directory.check_password(dn, password)
    except DirectoryError as exc:
        raise InvalidLoginError from exc
    if not ok:
        raise InvalidLoginError
    return dn


def parse_networks(values: Iterable[str]) -> list[IPNetwork]:
    """Parse IP addresses / CIDR ranges (``ValueError`` on malformed input)."""
    return [ipaddress.ip_network(v, strict=False) for v in values]


def is_trusted_proxy(ip: str | None, networks: Iterable[IPNetwork]) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def authenticate_header(
    directory: DirectoryClient,
    config: LoginConfig,
    *,
    peer_ip: str | None,
    trusted: Iterable[IPNetwork],
    header_value: str | None,
) -> str:
    """Trust ``header_value`` as the login when the request comes from a trusted proxy."""
    if not is_trusted_proxy(peer_ip, trusted) or not header_value:
        raise InvalidLoginError
    dn = find_user_dn(directory, config, header_value.strip())
    if dn is None:
        raise InvalidLoginError
    return dn
