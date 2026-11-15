"""Hash chain of the audit log: appending, concurrency and tamper detection."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from heracles.core import audit_chain as chain
from heracles.core.audit import audit_container, write_event
from heracles.ldap.client import DirectoryError, Modification
from heracles.ldap.memory import MemoryDirectory

BASE = "dc=test"
AUDIT = f"ou=audit,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    return d


def record(directory: MemoryDirectory, n: int = 1, **kw: str) -> list[str]:
    return [
        write_event(
            directory,
            action=kw.get("action", "modify"),
            object_type="user",
            object_dn=f"uid=u{i},ou=people,{BASE}",
            author_dn=kw.get("author", "uid=admin, ou=people, dc=test"),
            author_ip="10.0.0.1",
            attributes=["mail: a@b", "cn: Ann", "via: test"],
            now=NOW,
        )
        for i in range(n)
    ]


def verify(directory: MemoryDirectory) -> chain.Verification:
    return chain.verify_chain(directory, audit_container(directory))


def test_events_form_a_chain(directory: MemoryDirectory) -> None:
    dns = record(directory, 3)
    assert dns == [f"cn={i:010d},{AUDIT}" for i in (1, 2, 3)]
    first = directory.get(dns[0])
    second = directory.get(dns[1])
    assert first is not None and second is not None
    assert first.text(chain.PREVIOUS_ATTR) == chain.GENESIS
    assert second.text(chain.PREVIOUS_ATTR) == first.text(chain.HASH_ATTR)
    container = directory.get(AUDIT)
    assert container is not None and container.has_object_class(chain.CHAIN_CLASS)
    result = verify(directory)
    assert result.ok, result.first_break
    assert result.checked == 3
    assert result.head == chain.Link(3, directory.get(dns[2]).text(chain.HASH_ATTR))  # type: ignore[union-attr]


def test_hash_ignores_value_order_and_dn_spelling(directory: MemoryDirectory) -> None:
    (dn,) = record(directory)
    entry = directory.get(dn)
    assert entry is not None
    shuffled = dict(entry.attrs)
    shuffled["hrcAuditAttributes"] = list(reversed(shuffled["hrcAuditAttributes"]))
    shuffled["hrcAuditAuthorDN"] = [b"UID=admin,OU=people,DC=test"]
    seq = chain.sequence_of(entry)
    assert seq == 1
    assert chain.event_hash(shuffled, 1, chain.GENESIS) == entry.text(chain.HASH_ATTR)


def test_altered_event_is_detected(directory: MemoryDirectory) -> None:
    dns = record(directory, 4)
    directory.modify(dns[1], [Modification("replace", "hrcAuditObject", [b"uid=other,dc=test"])])
    result = verify(directory)
    assert not result.ok
    assert result.first_break == chain.Break(2, dns[1], "content altered (hash mismatch)")


def test_rehashed_event_breaks_the_next_link(directory: MemoryDirectory) -> None:
    dns = record(directory, 3)
    entry = directory.get(dns[1])
    assert entry is not None
    forged = dict(entry.attrs)
    forged["hrcAuditResult"] = [b"failure"]
    digest = chain.event_hash(forged, 2, entry.text(chain.PREVIOUS_ATTR) or "")
    directory.modify(
        dns[1],
        [
            Modification("replace", "hrcAuditResult", [b"failure"]),
            Modification("replace", chain.HASH_ATTR, [digest.encode()]),
        ],
    )
    result = verify(directory)
    assert result.first_break is not None
    assert result.first_break.sequence == 3
    assert result.first_break.reason == "does not link to the previous event"


def test_deleted_middle_event_is_detected(directory: MemoryDirectory) -> None:
    dns = record(directory, 4)
    directory.delete(dns[1])
    result = verify(directory)
    assert result.first_break is not None
    assert result.first_break.sequence == 2
    assert "missing" in result.first_break.reason


def test_deleted_newest_event_is_detected(directory: MemoryDirectory) -> None:
    dns = record(directory, 3)
    directory.delete(dns[2])
    result = verify(directory)
    assert result.first_break is not None
    assert result.first_break.sequence == 3
    assert "newest deleted" in result.first_break.reason


def test_stripping_the_chain_values_is_detected(directory: MemoryDirectory) -> None:
    dns = record(directory, 3)
    directory.modify(
        dns[1],
        [
            Modification("delete", chain.SEQUENCE_ATTR),
            Modification("delete", chain.HASH_ATTR),
            Modification("delete", chain.PREVIOUS_ATTR),
        ],
    )
    result = verify(directory)
    assert result.first_break is not None and result.first_break.sequence == 2


def test_deleted_head_is_detected(directory: MemoryDirectory) -> None:
    record(directory, 2)
    directory.modify(AUDIT, [Modification("delete", chain.HEAD_ATTR)])
    assert verify(directory).first_break == chain.Break(2, "", "chain head missing")


def test_base_hides_the_purged_range(directory: MemoryDirectory) -> None:
    dns = record(directory, 5)
    third = directory.get(dns[2])
    assert third is not None
    chain.set_base(directory, AUDIT, chain.Link(3, third.text(chain.HASH_ATTR) or ""))
    for dn in dns[:3]:
        directory.delete(dn)
    result = verify(directory)
    assert result.ok, result.first_break
    assert result.checked == 2
    # deleting the oldest remaining one is still caught
    directory.delete(dns[3])
    assert verify(directory).first_break is not None


def test_legacy_unchained_events_are_counted(directory: MemoryDirectory) -> None:
    write_event(
        directory, action="login", object_type="user", object_dn="x", author_dn="", chained=False
    )
    record(directory, 2)
    result = verify(directory)
    assert result.ok
    assert result.unchained == 1
    assert any("no sequence number" in w for w in result.warnings)


def test_lagging_head_is_caught_up(directory: MemoryDirectory) -> None:
    record(directory, 2)
    container = directory.get(AUDIT)
    assert container is not None
    stale = chain.head_of(container)
    assert stale is not None
    # a writer stopped after its add, before moving the head
    entry = directory.get(f"cn={2:010d},{AUDIT}")
    assert entry is not None
    directory.modify(
        AUDIT,
        [Modification("replace", chain.HEAD_ATTR, [b"1 " + entry.get(chain.PREVIOUS_ATTR)[0]])],
    )
    assert any("lags" in w for w in verify(directory).warnings)
    record(directory, 1)
    result = verify(directory)
    assert result.ok and result.checked == 3 and not result.warnings


def test_concurrent_writers_share_one_chain(directory: MemoryDirectory) -> None:
    errors: list[BaseException] = []

    def work() -> None:
        try:
            record(directory, 15)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    result = verify(directory)
    assert result.ok, result.first_break
    assert result.checked == 90
    assert result.unchained == 0


class _NoChainSchema(MemoryDirectory):
    """A server without the new schema: the container refuses the chain class."""

    def modify(self, dn: str, changes: object) -> None:  # type: ignore[override]
        if any(getattr(c, "attr", "") == chain.HEAD_ATTR for c in changes):  # type: ignore[attr-defined]
            raise DirectoryError("objectClass violation")
        super().modify(dn, changes)  # type: ignore[arg-type]


def test_old_schema_falls_back_to_unchained_events() -> None:
    d = _NoChainSchema(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    (dn,) = record(d)
    entry = d.get(dn)
    assert entry is not None
    assert entry.text("hrcAuditAction") == "modify"
    assert chain.sequence_of(entry) is None
