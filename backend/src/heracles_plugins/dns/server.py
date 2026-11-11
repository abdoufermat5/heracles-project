"""Authoritative DNS server answering from the zones stored in the directory.

dnspython is an optional dependency (extra ``dns``) imported lazily so the rest
of Heracles works without it.
"""

from __future__ import annotations

import contextlib
import importlib
import socket
import socketserver
import threading
import time
from collections.abc import Sequence
from types import ModuleType
from typing import Any, Final, cast

import structlog

from heracles.ldap.client import DirectoryClient
from heracles_plugins.dns.answer import (
    DEFAULT_TTL,
    Answer,
    Zone,
    load_zones,
    resolve,
    zone_for,
)
from heracles_plugins.dns.records import PSEUDO_TYPES, Record

log = structlog.get_logger(__name__)

_TCP_TIMEOUT: Final = 5.0


def _import_dns() -> ModuleType:
    try:
        module = importlib.import_module("dns")
        for name in ("dns.exception", "dns.flags", "dns.message", "dns.opcode", "dns.rcode"):
            importlib.import_module(name)
        importlib.import_module("dns.rdatatype")
        importlib.import_module("dns.rrset")
    except ImportError as exc:
        raise RuntimeError(
            "dnspython is not installed; install Heracles with the 'dns' extra"
        ) from exc
    return module


def _message_id(wire: bytes) -> int:
    return int.from_bytes(wire[:2], "big") if len(wire) >= 2 else 0


def _failure(dns: Any, ident: int, rcode: int) -> bytes:
    """A bare response carrying only an error code (the query was not usable)."""
    response = dns.message.Message(id=ident)
    response.flags = dns.flags.QR
    response.set_rcode(rcode)
    return response.to_wire()


def _absolute(name: str, zone: str | None) -> str:
    """Absolute owner name: relative names are composed with the zone origin."""
    if not zone:
        return name.rstrip(".") + "."
    if name == "@" or not name:
        return zone + "."
    return f"{name}.{zone}."


def _wire_type(rtype: str) -> str:
    return "TXT" if rtype in PSEUDO_TYPES else rtype


def _append(
    dns: Any, section: list[Any], records: Sequence[Record], ttl: int, zone: str | None
) -> None:
    """Append one RRset per (owner, type), keeping the record order."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for record in records:
        key = (_absolute(record.name, zone), _wire_type(record.type))
        grouped.setdefault(key, []).append(record.value)
    for (target, rtype), values in grouped.items():
        try:
            rrset = dns.rrset.from_text_list(target, ttl, "IN", rtype, values)
        except Exception:
            log.warning("dns_record_skipped", name=target, type=rtype, exc_info=True)
            continue
        section.append(rrset)


def _ttl_of(zones: Sequence[Zone], answer: Answer) -> int:
    if answer.zone is None:
        return DEFAULT_TTL
    zone = zone_for(zones, answer.zone)
    return zone.ttl if zone is not None else DEFAULT_TTL


class _UdpServer(socketserver.ThreadingUDPServer):
    """UDP server answering one datagram per request."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], dns_server: DnsServer) -> None:
        self.dns_server = dns_server
        super().__init__(address, _UdpHandler)


class _TcpServer(socketserver.ThreadingTCPServer):
    """TCP server reading length-prefixed requests."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], dns_server: DnsServer) -> None:
        self.dns_server = dns_server
        super().__init__(address, _TcpHandler)


class _UdpHandler(socketserver.BaseRequestHandler):
    """One datagram, one response; a broken datagram never stops the server."""

    def handle(self) -> None:
        server = cast(_UdpServer, self.server)
        payload, sock = cast(tuple[bytes, socket.socket], self.request)
        try:
            response = server.dns_server.handle(payload)
        except Exception:
            log.warning("dns_query_failed", exc_info=True)
            return
        with contextlib.suppress(OSError):
            sock.sendto(response, self.client_address)


class _TcpHandler(socketserver.BaseRequestHandler):
    """Requests on one connection, each prefixed with its two-byte length."""

    def handle(self) -> None:
        server = cast(_TcpServer, self.server)
        sock = cast(socket.socket, self.request)
        try:
            sock.settimeout(_TCP_TIMEOUT)
            while True:
                header = _recv_exact(sock, 2)
                if header is None:
                    return
                length = int.from_bytes(header, "big")
                if not length:
                    return
                body = _recv_exact(sock, length)
                if body is None:
                    return
                try:
                    response = server.dns_server.handle(body)
                except Exception:
                    log.warning("dns_query_failed", exc_info=True)
                    return
                sock.sendall(len(response).to_bytes(2, "big") + response)
        except OSError:
            return


def _recv_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class DnsServer:
    """Authoritative UDP/TCP server answering from the directory's DNS zones."""

    def __init__(
        self,
        directory: DirectoryClient,
        host: str = "127.0.0.1",
        port: int = 5353,
        *,
        tcp: bool = True,
        refresh: float = 5.0,
    ) -> None:
        self._directory = directory
        self._host = host
        self._port = port
        self._tcp = tcp
        self._refresh = refresh
        self._lock = threading.Lock()
        self._zones: list[Zone] = []
        self._loaded_at = 0.0
        self._udp: _UdpServer | None = None
        self._tcp_server: _TcpServer | None = None
        self._threads: list[threading.Thread] = []

    @property
    def bound_port(self) -> int:
        """Actual UDP port (``0`` in the constructor means an ephemeral one)."""
        server = self._udp
        return int(server.server_address[1]) if server is not None else self._port

    def start(self) -> None:
        """Load the zones, bind the sockets and serve in daemon threads."""
        _import_dns()
        if self._udp is not None:
            return
        self._reload()
        udp = _UdpServer((self._host, self._port), self)
        port = int(udp.server_address[1])
        tcp: _TcpServer | None = None
        if self._tcp:
            try:
                tcp = _TcpServer((self._host, port), self)
            except OSError:
                udp.server_close()
                raise
        self._udp = udp
        self._tcp_server = tcp
        self._threads = [self._serve(udp, "udp")]
        if tcp is not None:
            self._threads.append(self._serve(tcp, "tcp"))
        log.info("dns_server_listening", host=self._host, port=port, tcp=tcp is not None)

    def stop(self) -> None:
        """Stop answering, close the sockets and join the serving threads."""
        for server in (self._udp, self._tcp_server):
            if server is not None:
                server.shutdown()
                server.server_close()
        for thread in self._threads:
            thread.join(timeout=_TCP_TIMEOUT)
        self._udp = None
        self._tcp_server = None
        self._threads = []

    def handle(self, wire: bytes) -> bytes:
        """Turn one query message into one response message."""
        dns: Any = _import_dns()
        try:
            request = dns.message.from_wire(wire)
        except Exception:
            return _failure(dns, _message_id(wire), dns.rcode.FORMERR)
        if request.opcode() != dns.opcode.QUERY:
            response = dns.message.make_response(request)
            response.set_rcode(dns.rcode.NOTIMP)
            return response.to_wire()
        if not request.question:
            return _failure(dns, request.id, dns.rcode.FORMERR)
        question = request.question[0]
        zones = self._snapshot()
        answer = resolve(zones, question.name.to_text(), dns.rdatatype.to_text(question.rdtype))
        response = dns.message.make_response(request)
        response.flags |= dns.flags.AA
        ttl = _ttl_of(zones, answer)
        if answer.records:
            _append(dns, response.answer, answer.records, ttl, answer.zone)
        if answer.soa is not None:
            _append(dns, response.authority, (answer.soa,), ttl, answer.zone)
        if answer.nxdomain:
            response.set_rcode(dns.rcode.NXDOMAIN)
        return response.to_wire()

    # -- zone snapshot ---------------------------------------------------------

    def _reload(self) -> None:
        with self._lock:
            self._load_locked()

    def _snapshot(self) -> list[Zone]:
        with self._lock:
            stale = self._loaded_at == 0.0 or time.time() - self._loaded_at >= self._refresh
            if stale:
                self._load_locked()
            return self._zones

    def _load_locked(self) -> None:
        """Reload the zones; a failure keeps the previous snapshot."""
        try:
            self._zones = load_zones(self._directory)
        except Exception:
            log.warning("dns_zone_reload_failed", exc_info=True)
            return
        self._loaded_at = time.time()

    def _serve(self, server: socketserver.BaseServer, name: str) -> threading.Thread:
        thread = threading.Thread(target=server.serve_forever, name=f"dns-{name}", daemon=True)
        thread.start()
        return thread


def serve(directory: DirectoryClient, host: str, port: int, *, tcp: bool = True) -> None:
    """Serve until interrupted (Ctrl-C)."""
    server = DnsServer(directory, host, port, tcp=tcp)
    server.start()
    try:
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()
    finally:
        server.stop()
