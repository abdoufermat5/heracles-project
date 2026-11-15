"""Audit forwarding (formats, UDP/TCP/TLS), chain anchors and the retention policy."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import socket
import ssl
import threading
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from heracles.core import audit_chain as chain
from heracles.core.audit import audit_container, write_event
from heracles.ldap.memory import MemoryDirectory
from heracles.tasks.syslog import (
    AuditConfig,
    SyslogSender,
    SyslogSettings,
    configure_audit,
    format_record,
)
from heracles_plugins.audit.policy import (
    forward_events,
    purge_events,
    run_policy,
    send_anchor,
    throttle,
)

BASE = "dc=test"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    throttle.reset()
    yield
    configure_audit(None)
    throttle.reset()


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def record(
    directory: MemoryDirectory, n: int, *, days_ago: int = 0, action: str = "modify"
) -> None:
    for i in range(n):
        write_event(
            directory,
            action=action,
            object_type="user",
            object_dn=f"uid=u{i},{BASE}",
            author_dn=f"uid=admin,{BASE}",
            author_ip="10.0.0.9",
            attributes=["mail: a=b|c", "via: test"],
            now=NOW - timedelta(days=days_ago),
        )


class FakeSender:
    def __init__(self, fail_after: int | None = None) -> None:
        self.records: list[dict[str, object]] = []
        self.fail_after = fail_after

    def send_record(self, record: Mapping[str, Any], prefix: str = "") -> None:
        if self.fail_after is not None and len(self.records) >= self.fail_after:
            raise OSError("collector down")
        self.records.append(dict(record))


# -- formats ---------------------------------------------------------------------------------


EVENT = {
    "kind": "event",
    "sequence": 7,
    "hash": "ab" * 32,
    "previous": "cd" * 32,
    "dn": "cn=0000000007,ou=audit,dc=test",
    "time": "2030-06-15T08:00:00+00:00",
    "action": "modify",
    "type": "user",
    "object": "uid=ann,dc=test",
    "author": "uid=admin,dc=test",
    "ip": "10.0.0.9",
    "result": "success",
    "attributes": ["mail: a=b|c", "note: line\nbreak"],
}


def test_json_format_is_one_line() -> None:
    text = format_record(EVENT, "json")
    assert "\n" not in text
    assert json.loads(text)["sequence"] == 7


def test_cef_format_escapes_values() -> None:
    text = format_record(EVENT, "cef")
    assert text.startswith("CEF:0|Heracles|Heracles|")
    assert "|modify|modify user|3|" in text
    assert "cn1Label=sequence cn1=7" in text
    assert "msg=mail: a\\=b|c; note: line\\nbreak" in text
    assert "rt=1907740800000" in text
    assert "suser=uid\\=admin,dc\\=test" in text


def test_text_format_and_anchor() -> None:
    assert format_record(EVENT, "text", "[h] ").startswith("[h] 2030-06-15T08:00:00+00:00 modify")
    anchor = {"kind": "anchor", "sequence": 9, "hash": "ff"}
    assert format_record(anchor, "text") == "anchor sequence=9 hash=ff"
    assert "|anchor|Audit chain anchor|" in format_record(anchor, "cef")


def test_line_is_rfc5424() -> None:
    sender = SyslogSender(SyslogSettings(address="127.0.0.1:9", facility="local0"))
    line = sender.line("hello", now=NOW).decode()
    assert line.startswith("<134>1 2030-06-15T08:00:00.000Z ")
    assert line.endswith(" heracles - - - hello")


# -- transports ------------------------------------------------------------------------------


def test_udp_delivery() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(5)
    port = server.getsockname()[1]
    sender = SyslogSender(SyslogSettings(address=f"127.0.0.1:{port}", format="json"))
    sender.send_record(EVENT)
    data, _ = server.recvfrom(65535)
    server.close()
    sender.close()
    assert json.loads(data.decode().split(" - - - ", 1)[1])["hash"] == "ab" * 32


def _read_frames(conn: socket.socket, count: int) -> list[bytes]:
    buf = bytearray()
    frames: list[bytes] = []
    while len(frames) < count:
        chunk: bytes = conn.recv(65535)
        if not chunk:
            break
        buf.extend(chunk)
        while (space := buf.find(b" ")) >= 0:
            size = int(buf[:space])
            if len(buf) - space - 1 < size:
                break
            frames.append(bytes(buf[space + 1 : space + 1 + size]))
            del buf[: space + 1 + size]
    return frames


class _StreamServer:
    def __init__(self, context: ssl.SSLContext | None = None, count: int = 2) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.sock.settimeout(5)
        self.port = self.sock.getsockname()[1]
        self.frames: list[bytes] = []
        self._context = context
        self._count = count
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.sock.accept()
        if self._context is not None:
            conn = self._context.wrap_socket(conn, server_side=True)
        conn.settimeout(5)
        self.frames = _read_frames(conn, self._count)
        conn.close()

    def join(self) -> list[bytes]:
        self.thread.join(5)
        self.sock.close()
        return self.frames


def test_tcp_delivery_with_octet_counting() -> None:
    server = _StreamServer()
    sender = SyslogSender(
        SyslogSettings(address=f"127.0.0.1:{server.port}", transport="tcp", format="cef")
    )
    sender.send_record(EVENT)
    sender.send_record({"kind": "anchor", "sequence": 7, "hash": "ab" * 32})
    frames = server.join()
    sender.close()
    assert len(frames) == 2
    assert b"CEF:0|Heracles|Heracles|" in frames[0]
    assert b"|anchor|" in frames[1]


def _certificate(tmp: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp / "cert.pem", tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def test_tls_delivery_checks_the_collector(tmp_path: Path) -> None:
    cert, key = _certificate(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server = _StreamServer(context, count=3)
    sender = SyslogSender(
        SyslogSettings(
            address=f"localhost:{server.port}", transport="tls", format="json", ca_file=str(cert)
        )
    )
    for _ in range(3):
        sender.send_record(EVENT)
    sender.close()  # the last lines must survive the close
    frames = server.join()
    assert len(frames) == 3 and all(b'"sequence":7' in f for f in frames)


def test_tls_refuses_an_unknown_collector(tmp_path: Path) -> None:
    cert, key = _certificate(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def accept() -> None:
        conn, _ = server.accept()
        with contextlib.suppress(OSError, ssl.SSLError):
            context.wrap_socket(conn, server_side=True)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    sender = SyslogSender(SyslogSettings(address=f"localhost:{port}", transport="tls", timeout=3))
    with pytest.raises(OSError):  # ssl.SSLCertVerificationError is an OSError
        sender.send_record(EVENT)
    thread.join(5)
    server.close()


# -- forwarding position and anchors ---------------------------------------------------------


def test_forwarding_starts_at_the_head_and_follows(directory: MemoryDirectory) -> None:
    record(directory, 2)
    sender = FakeSender()
    assert forward_events(directory, sender) == 0  # history is not replayed
    record(directory, 3)
    assert forward_events(directory, sender) == 3
    assert [r["sequence"] for r in sender.records] == [3, 4, 5]
    assert forward_events(directory, sender) == 0


def test_failed_send_keeps_the_position(directory: MemoryDirectory) -> None:
    record(directory, 1)
    flaky = FakeSender(fail_after=1)
    forward_events(directory, flaky)
    record(directory, 3)
    assert forward_events(directory, flaky) == 1
    retry = FakeSender()
    assert forward_events(directory, retry) == 2
    assert [r["sequence"] for r in retry.records] == [3, 4]


def test_anchor_carries_the_head(directory: MemoryDirectory) -> None:
    record(directory, 2)
    sender = FakeSender()
    assert send_anchor(directory, sender, NOW)
    head = chain.head_of(chain.read_container(directory, audit_container(directory)))
    assert head is not None
    (anchor,) = sender.records
    assert anchor["kind"] == "anchor" and anchor["sequence"] == 2 and anchor["hash"] == head.hash


def test_policy_anchors_on_schedule(directory: MemoryDirectory) -> None:
    record(directory, 1)
    sender = FakeSender()
    config = AuditConfig.model_validate({"anchor_minutes": 60})
    assert run_policy(directory, NOW, config, sender).anchored
    assert not run_policy(directory, NOW + timedelta(minutes=10), config, sender).anchored
    assert run_policy(directory, NOW + timedelta(minutes=61), config, sender).anchored


# -- retention -------------------------------------------------------------------------------


def _actions(directory: MemoryDirectory) -> list[str]:
    found = directory.search(audit_container(directory), "(objectClass=hrcAuditEvent)")
    return sorted(e.text("hrcAuditAction") or "" for e in found)


def test_purge_by_age_keeps_the_chain_verifiable(directory: MemoryDirectory) -> None:
    record(directory, 3, days_ago=40)
    record(directory, 2, days_ago=1)
    result = purge_events(directory, NOW, days=30)
    assert result.purged == 3 and result.through == 3
    assert _actions(directory) == ["modify", "modify", "purge"]
    verification = chain.verify_chain(directory, audit_container(directory))
    assert verification.ok, verification.first_break
    assert verification.base.sequence == 3 and verification.checked == 3


def test_purge_by_count(directory: MemoryDirectory) -> None:
    record(directory, 6)
    result = purge_events(directory, NOW, count=2)
    assert result.purged == 4 and result.through == 4
    assert chain.verify_chain(directory, audit_container(directory)).ok


def test_purge_removes_old_unchained_events(directory: MemoryDirectory) -> None:
    write_event(
        directory,
        action="login",
        object_type="user",
        object_dn="x",
        author_dn="",
        now=NOW - timedelta(days=90),
        chained=False,
    )
    record(directory, 1, days_ago=1)
    assert purge_events(directory, NOW, days=30).purged == 1
    assert _actions(directory) == ["modify", "purge"]


def test_nothing_to_purge_writes_no_event(directory: MemoryDirectory) -> None:
    record(directory, 2)
    assert purge_events(directory, NOW, days=30).purged == 0
    assert _actions(directory) == ["modify", "modify"]


def test_policy_purge_is_throttled(directory: MemoryDirectory) -> None:
    config = AuditConfig.model_validate({"retention": {"count": 1}})
    record(directory, 3)
    assert run_policy(directory, NOW, config, None).purged == 2
    record(directory, 3)
    assert run_policy(directory, NOW + timedelta(minutes=5), config, None).purged == 0
    assert run_policy(directory, NOW + timedelta(hours=2), config, None).purged == 4
    assert chain.verify_chain(directory, audit_container(directory)).ok
