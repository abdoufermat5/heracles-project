import base64
import hashlib
from datetime import UTC, datetime

import pytest

from heracles.core.locks import LockedError, LockService
from heracles.ldap.memory import MemoryDirectory

ALICE = "uid=alice,ou=people,dc=heracles,dc=test"
CAROL = "uid=carol,ou=sub,ou=people,dc=heracles,dc=test"
OBJ = "uid=alice,ou=people,dc=heracles,dc=test"
OBJ2 = "ou=sub,ou=people,dc=heracles,dc=test"
FIXED = datetime(2024, 3, 5, 7, 8, 9, tzinfo=UTC)


@pytest.fixture
def svc(directory: MemoryDirectory) -> LockService:
    return LockService(directory, clock=lambda: FIXED)


def test_entry_format(svc: LockService, directory: MemoryDirectory) -> None:
    lock = svc.acquire(OBJ, CAROL)
    md5 = hashlib.md5(OBJ.encode()).hexdigest()
    assert lock.entry_dn == f"cn={md5},ou=locks,ou=heracles,dc=heracles,dc=test"
    entry = directory.get(lock.entry_dn)
    assert entry is not None
    assert entry.text("objectClass") == "hrcLockEntry"
    assert entry.text("cn") == md5
    assert entry.text("hrcUserDn") == CAROL
    assert entry.text("hrcObjectDn") == base64.b64encode(OBJ.encode()).decode()
    assert entry.text("hrcLockTimestamp") == "20240305070809Z"
    assert lock.acquired_at == FIXED


def test_acquire_same_user_is_noop(svc: LockService, directory: MemoryDirectory) -> None:
    first = svc.acquire(OBJ, CAROL)
    n = len(directory)
    assert svc.acquire(OBJ, CAROL.upper()) == first
    assert len(directory) == n


def test_acquire_conflict(svc: LockService) -> None:
    svc.acquire(OBJ, CAROL)
    with pytest.raises(LockedError) as info:
        svc.acquire(OBJ, ALICE)
    assert info.value.lock.user_dn == CAROL


def test_get(svc: LockService) -> None:
    assert svc.get(OBJ) is None  # container does not even exist yet
    svc.acquire(OBJ, CAROL)
    lock = svc.get(OBJ)
    assert lock is not None and lock.user_dn == CAROL and lock.object_dn == OBJ
    assert svc.get(OBJ2) is None


def test_release(svc: LockService) -> None:
    assert not svc.release(OBJ, CAROL)
    svc.acquire(OBJ, CAROL)
    assert not svc.release(OBJ, ALICE)  # not the holder
    assert svc.get(OBJ) is not None
    assert svc.release(OBJ, CAROL)
    assert svc.get(OBJ) is None
    svc.acquire(OBJ, ALICE)  # free again


def test_break_lock(svc: LockService) -> None:
    svc.acquire(OBJ, CAROL)
    assert svc.break_lock(OBJ)
    assert not svc.break_lock(OBJ)
    assert svc.get(OBJ) is None


def test_list_and_release_all(svc: LockService) -> None:
    assert svc.list_by_user(CAROL) == []
    svc.acquire(OBJ, CAROL)
    svc.acquire(OBJ2, CAROL)
    svc.acquire(CAROL, ALICE)
    assert {lk.object_dn for lk in svc.list_by_user(CAROL)} == {OBJ, OBJ2}
    assert len(svc.list_all()) == 3
    assert svc.release_all_for_user(CAROL) == 2
    assert svc.list_by_user(CAROL) == []
    assert [lk.object_dn for lk in svc.list_all()] == [CAROL]


def test_dn_with_special_chars(svc: LockService) -> None:
    odd = r"cn=Doe\, (J)*,ou=people,dc=heracles,dc=test"
    svc.acquire(odd, CAROL)
    lock = svc.get(odd)
    assert lock is not None and lock.object_dn == odd
