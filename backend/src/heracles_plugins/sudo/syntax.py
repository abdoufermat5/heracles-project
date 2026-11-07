"""Syntax checks for the ``sudoUser``, ``sudoHost``, ``sudoCommand`` and runas values."""

from __future__ import annotations

import ipaddress
import re
from typing import Final

from heracles.i18n import _

_NAME = r"[A-Za-z0-9_][A-Za-z0-9_.@-]*\$?"
_ID = r"[0-9]+"

#: ``login``, ``%group``, ``%#gid``, ``#uid``, ``+netgroup`` or ``ALL``.
_USER_RE: Final = re.compile(rf"ALL|{_NAME}|%:?{_NAME}|%#{_ID}|#{_ID}|\+{_NAME}")
#: ``ALL``, a group name or ``#gid`` (runas group).
_RUNAS_GROUP_RE: Final = re.compile(rf"ALL|{_NAME}|#{_ID}")
_HOSTNAME_RE: Final = re.compile(r"[A-Za-z0-9*?\[\]][A-Za-z0-9.*?\[\]_-]*")
_NETGROUP_RE: Final = re.compile(rf"\+{_NAME}")
_ALIAS_RE: Final = re.compile(r"[A-Z][A-Z0-9_]*")
_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f]")


def _strip_negation(value: str) -> str:
    return value[1:].lstrip() if value.startswith("!") else value


def user_error(value: str) -> str | None:
    """Problem with a ``sudoUser`` value, or ``None``."""
    if _USER_RE.fullmatch(_strip_negation(value)) is None:
        return _("Expected a login, %group, %#gid, #uid, +netgroup or ALL (optionally with '!').")
    return None


def runas_user_error(value: str) -> str | None:
    """Problem with a ``sudoRunAsUser`` value, or ``None`` (same syntax as ``sudoUser``)."""
    return user_error(value)


def runas_group_error(value: str) -> str | None:
    """Problem with a ``sudoRunAsGroup`` value, or ``None``."""
    if _RUNAS_GROUP_RE.fullmatch(_strip_negation(value)) is None:
        return _("Expected a group name, #gid or ALL (optionally with '!').")
    return None


def host_error(value: str) -> str | None:
    """Problem with a ``sudoHost`` value, or ``None``.

    Accepted: ``ALL``, a host name (globs allowed), an IP address, a CIDR network
    or ``address/netmask``, or a ``+netgroup``; each optionally prefixed by ``!``.
    """
    host = _strip_negation(value)
    if host == "ALL" or _HOSTNAME_RE.fullmatch(host) or _NETGROUP_RE.fullmatch(host):
        return None
    try:
        ipaddress.ip_network(host, strict=False)
    except ValueError:
        return _("Expected a host name, IP address, network (CIDR), +netgroup or ALL.")
    return None


def command_error(value: str) -> str | None:
    """Problem with a ``sudoCommand`` value, or ``None``.

    Accepted: ``ALL``; an absolute path (globs allowed) optionally followed by
    arguments; ``sudoedit``; a command alias name (upper case); each optionally
    prefixed by ``!``.
    """
    if _CONTROL_RE.search(value):
        return _("Control characters are not allowed.")
    command = _strip_negation(value).strip()
    if not command:
        return _("Expected a command.")
    head = command.split(None, 1)[0]
    if _ALIAS_RE.fullmatch(command) or head in ("sudoedit",) or head.startswith("/"):
        return None
    return _("Expected ALL, an absolute command path with optional arguments, or sudoedit.")


__all__ = [
    "command_error",
    "host_error",
    "runas_group_error",
    "runas_user_error",
    "user_error",
]
