import hashlib
import zlib
from collections.abc import Mapping, Sequence
from typing import cast

import pytest

from heracles.core.snapshots import SnapshotError, SnapshotService
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryError, Entry, NoSuchObjectError, Scope
from heracles.ldap.ldif import parse_ldif
from heracles.ldap.memory import MemoryDirectory
from tests.core.conftest import LDIF

SUB = "ou=sub,ou=people,dc=heracles,dc=test"
ALICE = "uid=alice,ou=people,dc=heracles,dc=test"
BASE = "ou=snapshots,dc=heracles,dc=test"


@pytest.fixture
def svc(directory: MemoryDirectory) -> SnapshotService:
    return SnapshotService(directory, clock=lambda: 1_700_000_000.123456)


def test_create_format(svc: SnapshotService, directory: MemoryDirectory) -> None:
    snap = svc.create(SUB, object_type="department", source="API", description="before cleanup")
    assert snap.dn == f"hrcSnapshotTimestamp=1700000000-012345600,{BASE}"
    entry = directory.get(snap.dn)
    assert entry is not None
    assert entry.text("objectClass") == "hrcSnapshotObject"
    assert entry.text("hrcSnapshotDN") == SUB
    assert entry.text("hrcSnapshotObjectType") == "department"
    assert entry.text("hrcSnapshotDataSource") == "API"
    assert entry.text("description") == "before cleanup"
    blob = entry.first("hrcSnapshotData")
    assert blob is not None
    raw = zlib.decompress(blob)
    assert entry.text("hrcSnapshotHash") == hashlib.md5(raw).hexdigest() == snap.hash
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
    assert a.timestamp == "1700000000-012345600"
    assert b.timestamp == "1700000000-012345700"


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


def test_prune_honours_retention_and_floor(directory: MemoryDirectory) -> None:
    now = [1_700_000_000.0]
    svc = SnapshotService(directory, clock=lambda: now[0])
    old = svc.create(ALICE, description="old")
    now[0] += 10 * 86_400
    middle = svc.create(ALICE, description="middle")
    now[0] += 10 * 86_400
    recent = svc.create(ALICE, description="recent")
    removed = svc.prune(retention_days=15)
    assert removed == [old.dn]
    assert {s.dn for s in svc.list_all()} == {middle.dn, recent.dn}
    # the floor wins over the retention
    assert svc.prune(retention_days=1, min_retention_days=100) == []
    assert svc.prune(retention_days=0) == []
    assert len(svc.list_all()) == 2


def test_corruption_detected(svc: SnapshotService, directory: MemoryDirectory) -> None:
    from heracles.ldap.client import Modification

    snap = svc.create(ALICE)
    directory.modify(snap.dn, [Modification("replace", "hrcSnapshotHash", [b"0" * 32])])
    with pytest.raises(SnapshotError):
        svc.ldif(snap.dn)
    directory.modify(snap.dn, [Modification("replace", "hrcSnapshotData", [b"not zlib"])])
    with pytest.raises(SnapshotError):
        svc.ldif(snap.dn)
    assert len(list(directory.search(BASE, scope=Scope.ONE))) == 1


def test_restore_refuses_entries_outside_the_snapshotted_subtree(
    svc: SnapshotService, directory: MemoryDirectory
) -> None:
    from heracles.ldap.client import Modification

    snap = svc.create(SUB)
    foreign = "dc=heracles,dc=test"
    forged = zlib.compress(
        (
            f"dn: {SUB}\nobjectClass: organizationalUnit\nou: sub\n\n"
            f"dn: cn=intruder,{foreign}\nobjectClass: organizationalRole\ncn: intruder\n"
        ).encode()
    )
    directory.modify(
        snap.dn,
        [
            Modification("replace", "hrcSnapshotData", [forged]),
            Modification("delete", "hrcSnapshotHash"),
        ],
    )
    with pytest.raises(SnapshotError):
        svc.restore(snap.dn)
    assert directory.get(f"uid=carol,{SUB}") is not None  # nothing was deleted
    assert directory.get(f"cn=intruder,{foreign}") is None


class _FlakyDirectory(MemoryDirectory):
    """A directory whose ``add`` fails for one DN (to exercise the restore rollback)."""

    def __init__(self, base_dn: str) -> None:
        super().__init__(base_dn)
        self.failing: str | None = None

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        if self.failing is not None and dnlib.normalize(dn) == dnlib.normalize(self.failing):
            raise DirectoryError("injected add failure")
        super().add(dn, attrs)


class _CountingDirectory(MemoryDirectory):
    """Counts single-entry reads (a batched lookup must not read every candidate)."""

    def __init__(self, base_dn: str) -> None:
        super().__init__(base_dn)
        self.get_calls = 0

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        self.get_calls += 1
        return super().get(dn, attrs)


def test_restore_failure_rolls_back_to_the_live_subtree() -> None:
    directory = cast("_FlakyDirectory", _FlakyDirectory.from_ldif(LDIF))
    svc = SnapshotService(directory, clock=lambda: 1_700_000_000.123456)
    snap = svc.create(SUB)
    directory.delete(f"uid=carol,{SUB}")
    extra = f"uid=extra,{SUB}"
    directory.add(extra, {"objectClass": [b"inetOrgPerson"], "sn": [b"E"]})
    directory.failing = f"uid=carol,{SUB}"

    with pytest.raises(DirectoryError):
        svc.restore(snap.dn)

    assert directory.get(extra) is not None  # the state before the attempt is back
    assert directory.get(f"uid=carol,{SUB}") is None
    assert len(svc.list_for_dn(SUB)) == 2  # the snapshot taken before the restore


def test_restore_failure_without_a_live_subtree_leaves_nothing() -> None:
    directory = cast("_FlakyDirectory", _FlakyDirectory.from_ldif(LDIF))
    svc = SnapshotService(directory, clock=lambda: 1_700_000_000.123456)
    snap = svc.create(SUB)
    directory.delete(SUB, recursive=True)
    directory.failing = f"uid=carol,{SUB}"

    with pytest.raises(DirectoryError):
        svc.restore(snap.dn)

    assert directory.get(SUB) is None


def test_list_deleted_reads_every_entry_in_one_search() -> None:
    directory = cast("_CountingDirectory", _CountingDirectory.from_ldif(LDIF))
    svc = SnapshotService(directory, clock=lambda: 1_700_000_000.123456)
    for dn in (
        SUB,
        f"uid=carol,{SUB}",
        ALICE,
        "ou=people,dc=heracles,dc=test",
        "dc=heracles,dc=test",
    ):
        svc.create(dn)
    directory.get_calls = 0

    assert svc.list_deleted() == []
    assert directory.get_calls == 0
