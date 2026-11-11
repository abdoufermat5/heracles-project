"""Audit forwarding to syslog.

Configuration (top level of the configuration file)::

    audit:
      syslog:
        address: "logs.example.org:514"   # "host:port" (UDP) or a socket path ("/dev/log")
        facility: local0

The audit task of the audit plugin logs the events to the ``heracles.audit`` logger; this
binds a ``SysLogHandler`` to it.
"""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Mapping
from typing import Any

import structlog
from pydantic import BaseModel

log = structlog.get_logger(__name__)

AUDIT_LOGGER = "heracles.audit"
_MARK = "_heracles_syslog"


class SyslogSettings(BaseModel):
    address: str = ""
    facility: str = "local0"


def _target(address: str) -> str | tuple[str, int]:
    if address.startswith("/"):
        return address
    host, sep, port = address.rpartition(":")
    if not sep or not host:
        return (address, logging.handlers.SYSLOG_UDP_PORT)
    return (host, int(port))


def configure_audit_syslog(raw: Mapping[str, Any] | None) -> bool:
    """Bind a syslog handler to the audit logger from the ``audit`` config section.

    Returns whether forwarding is configured. Calling it again replaces the handler.
    """
    section = (raw or {}).get("syslog")
    settings = SyslogSettings.model_validate(section or {})
    logger = logging.getLogger(AUDIT_LOGGER)
    for old in [h for h in logger.handlers if getattr(h, _MARK, False)]:
        logger.removeHandler(old)
        old.close()
    if not settings.address:
        return False
    facility = logging.handlers.SysLogHandler.facility_names.get(settings.facility)
    if facility is None:
        log.warning("audit.syslog_bad_facility", facility=settings.facility)
        return False
    try:
        handler = logging.handlers.SysLogHandler(_target(settings.address), facility=facility)
    except (OSError, ValueError) as exc:
        log.warning("audit.syslog_unavailable", address=settings.address, error=str(exc))
        return False
    setattr(handler, _MARK, True)
    handler.setFormatter(logging.Formatter("heracles-audit: %(message)s"))
    logger.addHandler(handler)
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    return True


def syslog_configured() -> bool:
    """Whether the audit logger currently forwards to syslog."""
    return any(getattr(h, _MARK, False) for h in logging.getLogger(AUDIT_LOGGER).handlers)
