"""Dataset of the benchmarks: the demo tree plus ``users`` accounts and ``users / 10`` groups.

The same deterministic data feeds the in-memory directory (:func:`load_memory`) and the real
OpenLDAP server (:func:`write_ldif`, loaded with ``slapadd``/``ldapadd`` by ``bench_ldap.py``).

Layout (``i`` is the user number, ``G`` the group count):

* user ``i`` lives in ``ou=people,ou=lyon`` when ``i % 5 < 2`` (40 %), else in
  ``ou=people,ou=paris`` (60 %); login ``user<i:05d>``, password :data:`PASSWORD` (salted SHA-1);
* group ``k`` lives in the same departments by the same rule, holds users ``i`` with
  ``i % G == k`` or ``(i + G // 2) % G == k`` (about 20 members, every user in two groups).

The demo already delegates Lyon to ``cdupont`` (role ``lyon-managers``, ACL role
``user-manager``): he is the non-administrator of the ACL scenarios.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from pathlib import Path

from heracles import demo
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry
from heracles.ldap.ldif import iter_ldif
from heracles.ldap.memory import MemoryDirectory

PASSWORD = "secret"  # noqa: S105 - password of every generated account
_SALT = b"hrcb"
#: Users whose password the in-memory directory knows (it does not verify salted hashes).
LOGIN_USERS = 10
#: Delegated administrator of Lyon (from the demo tree) and its password.
MANAGER_UID = "cdupont"
MANAGER_DN = f"uid={MANAGER_UID},ou=people,ou=lyon,{demo.BASE}"


def ssha(password: str) -> bytes:
    digest = hashlib.sha1(password.encode() + _SALT).digest()  # noqa: S324 - LDAP scheme
    return b"{SSHA}" + base64.b64encode(digest + _SALT)


def group_count(users: int) -> int:
    return max(10, users // 10)


def department(number: int) -> str:
    """Department of user or group ``number``."""
    return "lyon" if number % 5 < 2 else "paris"


def uid(i: int) -> str:
    return f"user{i:05d}"


def user_dn(i: int) -> str:
    return f"uid={uid(i)},ou=people,ou={department(i)},{demo.BASE}"


def group_dn(k: int) -> str:
    return f"cn=team{k:05d},ou=groups,ou={department(k)},{demo.BASE}"


def user_entry(i: int, hashed: bytes) -> Entry:
    return Entry(
        user_dn(i),
        {
            "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
            "uid": [uid(i).encode()],
            "givenName": [b"User"],
            "sn": [f"Number{i:05d}".encode()],
            "cn": [f"User Number{i:05d}".encode()],
            "mail": [f"{uid(i)}@heracles.test".encode()],
            "userPassword": [hashed],
        },
    )


def group_members(k: int, users: int, groups: int) -> list[int]:
    """User numbers belonging to group ``k`` (see the module docstring)."""
    first = {k % groups, (k - groups // 2) % groups}
    numbers = {i for start in first for i in range(start, users, groups)}
    return sorted(numbers) or [0]


def group_entry(k: int, users: int, groups: int) -> Entry:
    return Entry(
        group_dn(k),
        {
            "objectClass": [b"groupOfNames"],
            "cn": [f"team{k:05d}".encode()],
            "member": [user_dn(i).encode() for i in group_members(k, users, groups)],
        },
    )


def iter_bulk(users: int) -> Iterator[Entry]:
    """The generated users, then the groups."""
    hashed = ssha(PASSWORD)
    for i in range(users):
        yield user_entry(i, hashed)
    groups = group_count(users)
    for k in range(groups):
        yield group_entry(k, users, groups)


def demo_entries() -> list[Entry]:
    """The demo tree, parents before children (loadable into a real server)."""
    source = demo.build_demo_directory()
    entries: list[Entry] = []
    for dn in source.dns():
        entry = source.get(dn)
        assert entry is not None
        entries.append(entry)
    entries.sort(key=lambda e: len(dnlib.split(e.dn)))
    return entries


def _plain_passwords(entry: Entry) -> Entry:
    """OpenLDAP has no ``{CLEARTEXT}`` scheme (the demo uses it): store the password plain."""
    marker = b"{CLEARTEXT}"
    values = [v.removeprefix(marker) for v in entry.get("userPassword")]
    if not values or values == entry.get("userPassword"):
        return entry
    return Entry(entry.dn, {**entry.attrs, "userPassword": values})


def load_memory(directory: MemoryDirectory, users: int) -> None:
    """Fill an (empty) memory directory with the demo tree and the generated data."""
    source = demo.build_demo_directory()
    directory.set_schema_object_classes(source.schema_object_classes())
    for entry in demo_entries():
        directory.add(entry.dn, entry.attrs)
    for dn in (demo.ADMIN_DN, MANAGER_DN):
        directory.set_password(dn, demo.DEMO_PASSWORD)
    for entry in iter_bulk(users):
        directory.add(entry.dn, entry.attrs)
    for i in range(min(users, LOGIN_USERS)):
        directory.set_password(user_dn(i), PASSWORD)


def write_ldif(path: Path, users: int) -> int:
    """Write the whole dataset (demo tree first) as LDIF; return the entry count."""
    count = 0

    def entries() -> Iterator[Entry]:
        nonlocal count
        for entry in demo_entries():
            count += 1
            yield _plain_passwords(entry)
        for entry in iter_bulk(users):
            count += 1
            yield entry

    with path.open("w", encoding="utf-8") as out:
        for chunk in iter_ldif(entries(), wrap=0):
            out.write(chunk)
        out.write("\n")
    return count
