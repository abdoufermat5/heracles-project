"""Integration tests against a real server (see deploy/docker-compose.yml).

Run with ``HERACLES_TEST_LDAP_URI=ldap://localhost:1389`` (plus optionally
``HERACLES_TEST_LDAP_BIND_DN``, ``HERACLES_TEST_LDAP_BIND_PASSWORD`` and
``HERACLES_TEST_LDAP_BASE_DN``) and the ``ldap`` extra installed.
"""

import os
from collections.abc import Iterator

import pytest

from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Modification,
    NoSuchObjectError,
    Scope,
    SizeLimitExceededError,
)
from heracles.ldap.config import DirectoryConfig

URI = os.environ.get("HERACLES_TEST_LDAP_URI")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URI, reason="HERACLES_TEST_LDAP_URI not set"),
]

BASE = os.environ.get("HERACLES_TEST_LDAP_BASE_DN", "dc=heracles,dc=test")


@pytest.fixture
def directory() -> Iterator[DirectoryClient]:
    pytest.importorskip("ldap")
    from heracles.ldap.pyldap import PyLdapDirectory

    cfg = DirectoryConfig.model_validate(
        {
            "id": "test",
            "uri": URI,
            "base_dn": BASE,
            "bind_dn": os.environ.get("HERACLES_TEST_LDAP_BIND_DN", f"cn=admin,{BASE}"),
            "bind_password": os.environ.get("HERACLES_TEST_LDAP_BIND_PASSWORD", "admin"),
        }
    )
    d = PyLdapDirectory(cfg)
    yield d
    d.close()


def test_crud_cycle(directory: DirectoryClient) -> None:
    scratch = f"ou=it-scratch,{BASE}"
    directory.add(scratch, {"objectClass": [b"organizationalUnit"], "ou": [b"it-scratch"]})
    try:
        with pytest.raises(AlreadyExistsError):
            directory.add(scratch, {"objectClass": [b"organizationalUnit"], "ou": [b"it-scratch"]})
        for i in range(7):
            directory.add(
                f"cn=u{i},{scratch}",
                {"objectClass": [b"person"], "cn": [f"u{i}".encode()], "sn": [b"x"]},
            )
        assert len(list(directory.search(scratch, scope=Scope.ONE, page_size=3))) == 7
        with pytest.raises(SizeLimitExceededError):
            list(directory.search(scratch, scope=Scope.ONE, size_limit=2))
        directory.modify(f"cn=u0,{scratch}", [Modification("replace", "sn", [b"y"])])
        e = directory.get(f"cn=u0,{scratch}")
        assert e is not None and e.text("sn") == "y"
        new_dn = directory.rename(f"cn=u1,{scratch}", "cn=renamed")
        assert directory.get(new_dn) is not None
    finally:
        directory.delete(scratch, recursive=True)
    with pytest.raises(NoSuchObjectError):
        list(directory.search(scratch))


def test_schema_and_password(directory: DirectoryClient) -> None:
    assert "inetorgperson" in directory.schema_object_classes()
    assert not directory.check_password(f"cn=admin,{BASE}", "definitely-wrong")
    assert not directory.check_password(f"cn=admin,{BASE}", "")


def test_concurrent_operations(directory: DirectoryClient) -> None:
    """More parallel callers than pooled connections all get the right answer."""
    from concurrent.futures import ThreadPoolExecutor

    def read(_: int) -> str | None:
        entry = directory.get(BASE, ["objectClass"])
        return entry.dn if entry is not None else None

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(read, range(200)))
    assert set(results) == {BASE}
    # failing operations give their connection back: more failures than the pool holds
    for _ in range(20):
        with pytest.raises(NoSuchObjectError):
            list(directory.search(f"ou=missing,{BASE}"))
    assert read(0) == BASE
