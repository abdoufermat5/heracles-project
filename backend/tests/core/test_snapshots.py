import hashlib
import zlib

import pytest

from heracles.core.snapshots import SnapshotError, SnapshotService
from heracles.ldap.client import NoSuchObjectError, Scope
from heracles.ldap.ldif import parse_ldif
from heracles.ldap.memory import MemoryDirectory

SUB = "ou=sub,ou=people,dc=heracles,dc=test"
ALICE = "uid=alice,ou=people,dc=heracles,dc=test"
BASE = "ou=snapshots,dc=heracles,dc=test"


@pytest.fixture
def svc(directory: MemoryDirectory) -> SnapshotService:
    return SnapshotService(directory, clock=lambda: 1_700_000_000.123456)


def test_create_format(svc: SnapshotService, directory: MemoryDirectory) -> None:
    snap = svc.create(SUB, object_type="department", source="API", description="before cleanup")
    assert snap.dn == f"gosaSnapshotTimestamp=1700000000-123456,{BASE}"
    entry = directory.get(snap.dn)
    assert entry is not None
    assert entry.text("objectClass") == "gosaSnapshotObject"
    assert entry.text("gosaSnapshotDN") == SUB
    assert entry.text("fdSnapshotObjectType") == "department"
    assert entry.text("fdSnapshotDataSource") == "API"
    assert entry.text("description") == "before cleanup"
    blob = entry.first("gosaSnapshotData")
    assert blob is not None
    raw = zlib.decompress(blob)
    assert entry.text("fdSnapshotHash") == hashlib.md5(raw).hexdigest() == snap.hash
    dns = [e.dn for e in parse_ldif(raw.decode())]
    assert dns == [SUB, f"uid=carol,{SUB}"]  # whole subtree, parents first


def test_create_missing_object(svc: SnapshotService) -> None:
    with pytest.raises(NoSuchObjectError):
        svc.create("uid=ghost,dc=heracles,dc=test")


def test_timestamp_collision_retries(svc: SnapshotService) -> None:
    a = svc.create(ALICE)
    b = svc.create(ALICE)
    c = svc.create(ALICE)
    assert len({a.dn, b.dn, c.dn}) == 3
    assert a.timestamp == "1700000000-123456"
    assert b.timestamp == "1700000000-123457"


def test_list_for_dn_newest_first(svc: SnapshotService) -> None:
    assert svc.list_for_dn(ALICE) == []
    a = svc.create(ALICE, description="one")
    b = svc.create(ALICE, description="two")
    svc.create(SUB)
    listed = svc.list_for_dn(ALICE.upper())
    assert [s.dn for s in listed] == [b.dn, a.dn]
    assert listed[0].description == "two"
    assert listed[0].created_at is not None and listed[0].created_at.year == 2023
    assert len(svc.list_all()) == 3


def test_restore_replaces_subtree(svc: SnapshotService, directory: MemoryDirectory) -> None:
    snap = svc.create(SUB)
    directory.delete(f"uid=carol,{SUB}")
    directory.add(
        f"uid=extra,{SUB}", {"objectClass": [b"inetOrgPerson"], "cn": [b"E"], "sn": [b"E"]}
    )
    restored = svc.restore(snap.dn)
    assert restored == [SUB, f"uid=carol,{SUB}"]
    assert directory.get(f"uid=extra,{SUB}") is None
    assert directory.get(f"uid=carol,{SUB}") is not None


def test_restore_deleted_object_with_binary_value(
    svc: SnapshotService, directory: MemoryDirectory
) -> None:
    snap = svc.create(ALICE)
    directory.delete(ALICE)
    assert [s.dn for s in svc.list_deleted()] == [snap.dn]
    svc.restore(snap.dn)
    again = directory.get(ALICE)
    assert again is not None and again.text("displayName") == "Café"
    assert svc.list_deleted() == []


def test_restore_requires_parent(svc: SnapshotService, directory: MemoryDirectory) -> None:
    snap = svc.create(f"uid=carol,{SUB}")
    directory.delete(SUB, recursive=True)
    with pytest.raises(NoSuchObjectError):
        svc.restore(snap.dn)


def test_list_deleted_latest_only_and_scope(
    svc: SnapshotService, directory: MemoryDirectory
) -> None:
    svc.create(ALICE)
    newest = svc.create(ALICE)
    other = svc.create(f"uid=carol,{SUB}")
    directory.delete(ALICE)
    directory.delete(f"uid=carol,{SUB}")
    assert {s.dn for s in svc.list_deleted()} == {newest.dn, other.dn}
    assert [s.dn for s in svc.list_deleted(under=SUB)] == [other.dn]


def test_delete(svc: SnapshotService, directory: MemoryDirectory) -> None:
    snap = svc.create(ALICE)
    assert svc.get(snap.dn) == snap
    svc.delete(snap.dn)
    assert svc.get(snap.dn) is None
    assert directory.get(snap.dn) is None


def test_corruption_detected(svc: SnapshotService, directory: MemoryDirectory) -> None:
    from heracles.ldap.client import Modification

    snap = svc.create(ALICE)
    directory.modify(snap.dn, [Modification("replace", "fdSnapshotHash", [b"0" * 32])])
    with pytest.raises(SnapshotError):
        svc.ldif(snap.dn)
    directory.modify(snap.dn, [Modification("replace", "gosaSnapshotData", [b"not zlib"])])
    with pytest.raises(SnapshotError):
        svc.ldif(snap.dn)
    assert len(list(directory.search(BASE, scope=Scope.ONE))) == 1
