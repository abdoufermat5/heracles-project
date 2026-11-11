"""Audit sink: one place to write audit events from anywhere in the application.

The ``audit`` plugin owns the ``audit_event`` type and the ``ou=audit`` container; this
module holds the writing code so that code outside the object service (login, second
factors, recovery, ACL and configuration changes, imports ...) can record events too.

:class:`AuditSink` is bound to the type registry: it does nothing while the audit plugin is
not enabled, and it never raises into the caller (an audit failure must not break the
audited operation).
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from heracles.core.containers import ensure_container
from heracles.core.generalized_time import format_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient

if TYPE_CHECKING:
    from heracles.objects.registry import TypeRegistry

log = structlog.get_logger(__name__)

EVENT_CLASS = "hrcAuditEvent"
AUDIT_RDN = "ou=audit"
EVENT_TYPE = "audit_event"
PLUGIN_NAME = "audit"

#: Actions recorded by the object service.
OBJECT_ACTIONS = ("create", "modify", "delete")
#: Actions recorded for events outside the object service.
EXTRA_ACTIONS = (
    "login",
    "login_failed",
    "logout",
    "password",
    "second_factor",
    "acl",
    "config",
    "import",
    "task",
)
ACTIONS = (*OBJECT_ACTIONS, *EXTRA_ACTIONS)
#: Attribute values longer than this are cut in the log.
MAX_VALUE_LENGTH = 256
#: Number of attributes recorded per event.
MAX_ATTRIBUTES = 100


class AuthorLike(Protocol):
    """What :meth:`AuditSink.record_by` needs from the acting user (``CurrentUser``)."""

    @property
    def directory(self) -> DirectoryClient: ...

    @property
    def dn(self) -> str: ...

    @property
    def client_ip(self) -> str: ...


def audit_container(directory: DirectoryClient) -> str:
    return dnlib.join(AUDIT_RDN, directory.base_dn)


def write_event(
    directory: DirectoryClient,
    *,
    action: str,
    object_type: str,
    object_dn: str,
    author_dn: str,
    author_ip: str = "",
    attributes: Sequence[str] = (),
    result: str = "success",
    now: datetime | None = None,
) -> str:
    """Create one event entry and return its DN (``author_dn`` may be empty: unknown author)."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    container = audit_container(directory)
    ensure_container(directory, container)
    cn = f"{moment.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
    attrs: dict[str, list[bytes]] = {
        "objectClass": [EVENT_CLASS.encode()],
        "cn": [cn.encode()],
        "hrcAuditDateTime": [format_generalized_time(moment).encode()],
        "hrcAuditAction": [action.encode()],
        "hrcAuditObjectType": [object_type.encode()],
        "hrcAuditObject": [object_dn.encode()],
        "hrcAuditResult": [result.encode()],
    }
    if author_dn:
        attrs["hrcAuditAuthorDN"] = [author_dn.encode()]
    if author_ip:
        attrs["hrcAuditAuthorIP"] = [author_ip.encode()]
    if attributes:
        attrs["hrcAuditAttributes"] = [a.encode() for a in attributes[:MAX_ATTRIBUTES]]
    dn = f"cn={cn},{container}"
    directory.add(dn, attrs)
    return dn


def _cut(text: str) -> str:
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 3] + "..."


class AuditSink:
    """Records audit events when the audit plugin is enabled; otherwise a no-op."""

    def __init__(self, registry: TypeRegistry | None = None) -> None:
        self._registry = registry

    def attach(self, registry: TypeRegistry) -> None:
        """Bind the sink to the registry once plugins are loaded."""
        self._registry = registry

    @property
    def enabled(self) -> bool:
        if self._registry is None:
            return False
        try:
            self._registry.get(EVENT_TYPE)
        except Exception:
            return False
        return True

    def _allowed(self, action: str) -> bool:
        assert self._registry is not None
        settings: Any = self._registry.settings.get(PLUGIN_NAME)
        actions = getattr(settings, "actions", None)
        return actions is None or action in actions

    def record(
        self,
        directory: DirectoryClient,
        action: str,
        *,
        object_type: str,
        object_dn: str,
        author_dn: str = "",
        author_ip: str = "",
        attributes: Sequence[str] = (),
        result: str = "success",
        source: str = "api",
    ) -> None:
        """Write one event. Never raises. ``source`` is noted when it is not ``api``."""
        try:
            if not self.enabled or not self._allowed(action):
                return
            lines = [_cut(a) for a in attributes]
            if source != "api":
                lines.append(f"source: {source}")
            write_event(
                directory,
                action=action,
                object_type=object_type,
                object_dn=object_dn,
                author_dn=author_dn,
                author_ip=author_ip,
                attributes=lines,
                result=result,
            )
        except Exception as exc:
            log.warning("audit_event_failed", action=action, error=type(exc).__name__)

    def record_by(
        self,
        user: AuthorLike,
        action: str,
        *,
        object_type: str,
        object_dn: str,
        attributes: Sequence[str] = (),
        result: str = "success",
        source: str = "api",
    ) -> None:
        """:meth:`record` with the acting user's directory, DN and address."""
        self.record(
            user.directory,
            action,
            object_type=object_type,
            object_dn=object_dn,
            author_dn=user.dn,
            author_ip=user.client_ip,
            attributes=attributes,
            result=result,
            source=source,
        )


__all__ = [
    "ACTIONS",
    "AUDIT_RDN",
    "EVENT_CLASS",
    "EXTRA_ACTIONS",
    "AuditSink",
    "audit_container",
    "write_event",
]
