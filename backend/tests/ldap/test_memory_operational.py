"""Operational attributes of the in-memory directory (entryUUID, timestamps)."""

from __future__ import annotations

from heracles.ldap.memory import MemoryDirectory

BASE = "dc=example,dc=com"


def _directory() -> tuple[MemoryDirectory, str]:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"example"]})
    d.add(f"ou=people,{BASE}", {"objectClass": [b"organizationalUnit"]})
    dn = f"uid=jdoe,ou=people,{BASE}"
    d.add(dn, {"objectClass": [b"inetOrgPerson"], "sn": [b"Doe"], "cn": [b"J"]})
    return d, dn


def test_operational_attributes_only_when_asked() -> None:
    d, dn = _directory()
    plain = d.get(dn)
    assert plain is not None and plain.get("entryUUID") == []
    star = d.get(dn, ["*"])
    assert star is not None and star.get("entryUUID") == []
    asked = d.get(dn, ["entryUUID", "createTimestamp"])
    assert asked is not None and asked.text("entryUUID") and asked.text("createTimestamp")
    assert asked.get("sn") == []
    every = d.get(dn, ["*", "+"])
    assert every is not None and every.text("sn") == "Doe" and every.text("modifyTimestamp")


def test_entry_uuid_is_searchable_and_survives_a_rename() -> None:
    d, dn = _directory()
    found = d.get(dn, ["entryUUID"])
    assert found is not None
    uid = found.text("entryUUID")
    (hit,) = list(d.search(BASE, f"(entryUUID={uid})"))
    assert hit.dn == dn
    new_dn = d.rename(dn, "uid=jsmith")
    moved = d.get(new_dn, ["entryUUID"])
    assert moved is not None and moved.text("entryUUID") == uid
    assert d.get(dn) is None


def test_modify_updates_the_timestamp_and_delete_forgets() -> None:
    d, dn = _directory()
    d.delete(dn)
    assert list(d.search(BASE, "(entryUUID=*)", attrs=["entryUUID"])) != []
    assert all(e.dn != dn for e in d.search(BASE, "(entryUUID=*)"))
