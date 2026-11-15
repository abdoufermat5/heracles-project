"""Audit policy and forwarding: retention, chain anchors and syslog delivery.

Configuration (top level of the configuration file)::

    audit:
      retention:
        days: 365            # purge events older than this (0 or absent: keep)
        count: 0             # keep at most this many events (0 or absent: no limit)
      anchor_minutes: 60     # write the chain head to the syslog stream this often
      syslog:
        address: "logs.example.org:6514"  # "host:port", or a socket path ("/dev/log")
        transport: tls       # udp (default), tcp or tls; ignored for a socket path
        format: json         # text (default), json or cef
        framing: octet-counting   # tcp/tls: octet-counting (default) or newline
        facility: local0
        ca_file: /etc/ssl/certs/log-ca.pem   # tls: trusted authorities (default: system)
        cert_file: ""        # tls: client certificate, when the collector asks for one
        key_file: ""
        verify: true         # tls: check the collector certificate and name
        timeout: 5           # seconds, for connecting and sending

Each message is an RFC 5424 syslog line (``<PRI>1 TIME HOST heracles - - - MSG``); the
scheduler sends the events in chain order and keeps its position on the audit container
(``hrcAuditForwarded``), so a collector that was down receives the backlog later.
"""

from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import socket
import ssl
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel, ConfigDict

from heracles import __version__

log = structlog.get_logger(__name__)

AUDIT_LOGGER = "heracles.audit"
APP_NAME = "heracles"
#: Longest UDP datagram sent (longer messages are cut).
MAX_DATAGRAM = 8192


class RetentionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = 0
    count: int = 0

    @property
    def active(self) -> bool:
        return self.days > 0 or self.count > 0


class SyslogSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = ""
    facility: str = "local0"
    transport: Literal["udp", "tcp", "tls"] = "udp"
    format: Literal["text", "json", "cef"] = "text"
    framing: Literal["octet-counting", "newline"] = "octet-counting"
    ca_file: str = ""
    cert_file: str = ""
    key_file: str = ""
    verify: bool = True
    timeout: float = 5.0


class AuditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention: RetentionSettings = RetentionSettings()
    anchor_minutes: int = 60
    syslog: SyslogSettings = SyslogSettings()


# -- message formats ---------------------------------------------------------------------------


def _cef_header(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _cef_value(text: str) -> str:
    return text.replace("\\", "\\\\").replace("=", "\\=").replace("\r", "\\r").replace("\n", "\\n")


def _epoch_ms(iso: str) -> str:
    try:
        return str(int(datetime.fromisoformat(iso).timestamp() * 1000))
    except ValueError:
        return ""


def format_record(record: Mapping[str, Any], fmt: str, prefix: str = "") -> str:
    """One event (or anchor) as message text.

    ``record`` holds ``kind`` (``event`` or ``anchor``) and the event fields
    (:func:`heracles.core.audit_chain.event_record`).
    """
    if fmt == "json":
        return json.dumps(dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if fmt == "cef":
        anchor = record.get("kind") == "anchor"
        signature = "anchor" if anchor else str(record.get("action", ""))
        name = (
            "Audit chain anchor"
            if anchor
            else f"{record.get('action', '')} {record.get('type', '')}"
        )
        severity = 5 if record.get("result") == "failure" else 3
        ext: list[tuple[str, str]] = [
            ("rt", _epoch_ms(str(record.get("time", "")))),
            ("cn1Label", "sequence"),
            ("cn1", str(record.get("sequence", ""))),
            ("cs1Label", "hash"),
            ("cs1", str(record.get("hash", ""))),
        ]
        if not anchor:
            ext += [
                ("act", str(record.get("action", ""))),
                ("outcome", str(record.get("result", ""))),
                ("suser", str(record.get("author", ""))),
                ("src", str(record.get("ip", ""))),
                ("cs2Label", "objectType"),
                ("cs2", str(record.get("type", ""))),
                ("cs3Label", "object"),
                ("cs3", str(record.get("object", ""))),
                ("msg", "; ".join(record.get("attributes") or [])),
            ]
        extension = " ".join(f"{k}={_cef_value(v)}" for k, v in ext if v)
        return (
            f"CEF:0|Heracles|Heracles|{_cef_header(__version__)}|{_cef_header(signature)}|"
            f"{_cef_header(name)}|{severity}|{extension}"
        )
    if record.get("kind") == "anchor":
        return f"{prefix}anchor sequence={record.get('sequence')} hash={record.get('hash')}"
    attributes = "; ".join(record.get("attributes") or [])
    text = (
        f"{record.get('time', '')} {record.get('action', '')} {record.get('type', '')} "
        f"{record.get('object', '')} by={record.get('author') or '-'} "
        f"ip={record.get('ip') or '-'} result={record.get('result', '')} "
        f"sequence={record.get('sequence', '')}"
    )
    return f"{prefix}{text}" + (f" [{attributes}]" if attributes else "")


# -- transport ---------------------------------------------------------------------------------


def _target(address: str) -> str | tuple[str, int]:
    if address.startswith("/"):
        return address
    host, sep, port = address.rpartition(":")
    if not sep or not host:
        return (address, logging.handlers.SYSLOG_UDP_PORT)
    return (host.strip("[]"), int(port))


class RecordSender(Protocol):
    """What the forwarding needs: :meth:`SyslogSender.send_record`."""

    def send_record(self, record: Mapping[str, Any], prefix: str = "") -> None: ...


class SyslogSender:
    """Delivers audit messages to one collector; :meth:`send` raises ``OSError`` on failure."""

    def __init__(self, settings: SyslogSettings) -> None:
        facility = logging.handlers.SysLogHandler.facility_names.get(settings.facility)
        if facility is None:
            raise ValueError(f"unknown syslog facility {settings.facility!r}")
        self.settings = settings
        self._facility = facility
        self._target = _target(settings.address)
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._hostname = socket.gethostname() or "-"
        if settings.transport == "tls" and not isinstance(self._target, str):
            self._tls = self._tls_context(settings)
        else:
            self._tls = None

    @staticmethod
    def _tls_context(settings: SyslogSettings) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=settings.ca_file or None)
        if settings.cert_file:
            context.load_cert_chain(settings.cert_file, settings.key_file or None)
        if not settings.verify:
            log.warning("audit.syslog_tls_unverified", address=settings.address)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context

    @property
    def stream(self) -> bool:
        return not isinstance(self._target, str) and self.settings.transport in ("tcp", "tls")

    def line(self, message: str, *, severity: int = 6, now: datetime | None = None) -> bytes:
        stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="milliseconds")
        pri = self._facility * 8 + severity
        head = f"<{pri}>1 {stamp.replace('+00:00', 'Z')} {self._hostname} {APP_NAME} - - - "
        return (head + message).encode("utf-8")

    def _connect(self) -> socket.socket:
        timeout = self.settings.timeout
        target = self._target
        if isinstance(target, str):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            try:
                sock.connect(target)
            except OSError:
                sock.close()
                raise
            return sock
        if not self.stream:
            family = socket.getaddrinfo(target[0], target[1], type=socket.SOCK_DGRAM)[0][0]
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.connect(target)
            return sock
        raw = socket.create_connection(target, timeout=timeout)
        if self._tls is None:
            return raw
        try:
            return self._tls.wrap_socket(raw, server_hostname=target[0])
        except (OSError, ssl.SSLError):
            raw.close()
            raise

    def _frame(self, payload: bytes) -> bytes:
        if not self.stream:
            return payload[:MAX_DATAGRAM]
        if self.settings.framing == "newline":
            return payload.replace(b"\n", b" ") + b"\n"
        return str(len(payload)).encode() + b" " + payload

    def send(self, message: str, *, severity: int = 6) -> None:
        data = self._frame(self.line(message, severity=severity))
        with self._lock:
            for attempt in (0, 1):
                if self._sock is None:
                    self._sock = self._connect()
                try:
                    self._sock.sendall(data)
                    return
                except OSError:
                    self._close()
                    if attempt:
                        raise

    def send_record(self, record: Mapping[str, Any], prefix: str = "") -> None:
        severity = 5 if record.get("result") == "failure" else 6
        self.send(format_record(record, self.settings.format, prefix), severity=severity)

    def _close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        if self.stream:
            # Half-close, then read what the collector sent (TLS session tickets): closing
            # with unread data resets the connection, and the collector drops the last lines.
            with contextlib.suppress(OSError, ValueError):
                sock.settimeout(min(self.settings.timeout, 1.0))
                sock.shutdown(socket.SHUT_WR)
                while sock.recv(4096):
                    pass
        with contextlib.suppress(OSError):
            sock.close()

    def close(self) -> None:
        with self._lock:
            self._close()


# -- process-wide configuration ----------------------------------------------------------------

_config = AuditConfig()
_sender: SyslogSender | None = None


def configure_audit(raw: Mapping[str, Any] | None) -> AuditConfig:
    """Read the ``audit`` section (retention, anchors, syslog); replaces the previous one."""
    global _config, _sender
    try:
        config = AuditConfig.model_validate(dict(raw or {}))
    except ValueError as exc:
        log.warning("audit.config_invalid", error=str(exc))
        config = AuditConfig()
    if _sender is not None:
        _sender.close()
    _sender = None
    _config = config
    if config.syslog.address:
        try:
            _sender = SyslogSender(config.syslog)
        except (OSError, ValueError, ssl.SSLError) as exc:
            log.warning("audit.syslog_unavailable", address=config.syslog.address, error=str(exc))
    return config


def configure_audit_syslog(raw: Mapping[str, Any] | None) -> bool:
    """:func:`configure_audit`; returns whether syslog forwarding is configured."""
    configure_audit(raw)
    return _sender is not None


def audit_config() -> AuditConfig:
    return _config


def audit_sender() -> SyslogSender | None:
    return _sender


def syslog_configured() -> bool:
    """Whether the audit events are forwarded to a collector."""
    return _sender is not None


__all__ = [
    "AUDIT_LOGGER",
    "AuditConfig",
    "RecordSender",
    "RetentionSettings",
    "SyslogSender",
    "SyslogSettings",
    "audit_config",
    "audit_sender",
    "configure_audit",
    "configure_audit_syslog",
    "format_record",
    "syslog_configured",
]
