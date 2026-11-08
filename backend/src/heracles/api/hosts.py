"""The public address of the console, for links the server builds (CAS callback, invitations).

The configured public address is always preferred. Without one, the address of the request is
used only when its ``Host`` header names an allowed host: the header is chosen by the client,
and a link built from an arbitrary value could point a ticket or an e-mailed token at an
attacker's server.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import structlog
from fastapi import Request

from heracles.api.errors import ApiError

_HOST_RE = re.compile(r"[A-Za-z0-9.\-]+(:\d{1,5})?|\[[0-9A-Fa-f:.]+\](:\d{1,5})?")

log = structlog.get_logger(__name__)

#: ``allowed_hosts`` default: the local development and test addresses.
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "[::1]", "testserver")


def host_allowed(host: str, allowed: list[str]) -> bool:
    """Whether the host name of a ``Host`` header is in ``allowed``.

    Entries are host names compared case-insensitively without the port; ``*.example.org``
    matches any subdomain of ``example.org`` (not the domain itself).
    """
    if not _HOST_RE.fullmatch(host):  # no userinfo, path or backslash tricks
        return False
    try:
        name = urlsplit(f"//{host}").hostname
    except ValueError:
        return False
    if not name:
        return False
    if ":" in name:  # IPv6 literal: hostname drops the brackets
        name = f"[{name}]"
    name = name.lower().rstrip(".")
    for pattern in allowed:
        pattern = pattern.strip().lower().rstrip(".")
        if pattern.startswith("*."):
            if name.endswith(pattern[1:]) and len(name) > len(pattern) - 1:
                return True
        elif pattern and name == pattern:
            return True
    return False


def request_base(request: Request, allowed: list[str], *, setting: str) -> str:
    """Base URL (no trailing slash) of the request, if its ``Host`` is allowed.

    ``setting`` names the option that fixes the public address, for the error message.
    """
    host = request.headers.get("host", "")
    if not host_allowed(host, allowed):
        log.warning("untrusted_host", host=host[:255], path=request.url.path)
        raise ApiError(
            400,
            "untrusted_host",
            f"The host '{host[:100]}' is not allowed: configure {setting} "
            "or add the host to api.allowed_hosts",
        )
    return str(request.base_url).rstrip("/")


__all__ = ["DEFAULT_ALLOWED_HOSTS", "host_allowed", "request_base"]
