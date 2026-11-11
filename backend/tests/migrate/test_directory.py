"""Migration of a legacy directory export to the Heracles schema.

This test module (with ``legacy_map.py``) is allowed to spell legacy identifiers.
"""

from __future__ import annotations

import base64
import hashlib
import zlib

from heracles.acl.model import Ignored
from heracles.acl.parser import parse_assignment, parse_role_value
from heracles.ldap.client import Entry
from heracles.ldap.ldif import dump_ldif, parse_ldif
from heracles.migrate.directory import migrate_entries, migrate_ldif

BASE = "dc=example,dc=org"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _entry(dn: str, **attrs: list[str] | list[bytes]) -> Entry:
    return Entry(
        dn=dn,
        attrs={
            k: [v if isinstance(v, bytes) else v.encode() for v in vs] for k, vs in attrs.items()
        },
    )


def _by_dn(entries: list[Entry]) -> dict[str, Entry]:
    return {e.dn: e for e in entries}


def _classes(entry: Entry) -> set[str]:
    return {c.decode() for c in entry.get("objectClass")}


def test_entry_names_and_dns_are_renamed() -> None:
    legacy = [
        _entry(
            f"ou=sales,{BASE}",
            objectClass=["organizationalUnit", "gosaDepartment"],
            ou=["sales"],
            description=["Sales"],
        ),
        _entry(
            f"cn=config,ou=fusiondirectory,{BASE}",
            objectClass=["fusionDirectoryConf", "fusionDirectoryPluginsConf"],
            cn=["config"],
            fdUserRDN=["ou=people"],
            fdSchemaCheck=["true"],
            fdAccountPrimaryAttribute=["uid"],
        ),
    ]
    out, report = migrate_entries(legacy)
    assert report.errors == []
    entries = _by_dn(out)
    dept = entries[f"ou=sales,{BASE}"]
    assert _classes(dept) == {"organizationalUnit", "hrcDepartment"}
    conf = entries[f"cn=config,ou=heracles,{BASE}"]
    assert _classes(conf) == {"hrcConf", "hrcPluginsConf"}
    assert conf.text("hrcUserRDN") == "ou=people"
    assert conf.text("hrcSchemaCheck") == "TRUE"  # boolean normalised
    assert ("fdUserRDN", "hrcUserRDN") in report.rename_table()


def test_personal_and_macro_attributes_get_their_classes() -> None:
    user = _entry(
        f"uid=ann,ou=people,{BASE}",
        objectClass=["inetOrgPerson", "fdPersonalInfo"],
        uid=["ann"],
        cn=["Ann"],
        sn=["Lee"],
        dateOfBirth=["1990-03-25"],
        gender=["F"],
        phoneMacro=["stdexten"],
    )
    out, report = migrate_entries([user])
    assert report.errors == []
    (entry,) = out
    assert entry.text("hrcDateOfBirth") == "1990-03-25"
    assert entry.text("hrcGender") == "F"
    assert entry.text("hrcPhoneMacroContent") == "stdexten"
    assert _classes(entry) == {"inetOrgPerson", "hrcPersonalInfo", "hrcPhoneMacroUser"}
    assert report.added_classes["hrcPhoneMacroUser"] == 1


def test_acl_values_are_rewritten() -> None:
    role = _entry(
        f"cn=editor,ou=aclroles,{BASE}",
        objectClass=["gosaRole"],
        cn=["editor"],
        gosaAclTemplate=["0:user/user;rw#fdNickName;r#sn;rw"],
    )
    assignment = _entry(
        BASE,
        objectClass=["dcObject", "organization", "gosaAcl"],
        gosaAclEntry=[
            f"0:subtree:{_b64(f'cn=editor,ou=aclroles,{BASE}')}:{_b64('*')}"
            f":{_b64('(objectClass=gosaMailAccount)')}"
        ],
    )
    out, report = migrate_entries([role, assignment])
    assert report.errors == []
    entries = _by_dn(out)
    template = parse_role_value(entries[role.dn].texts("hrcAclTemplate")[0])
    assert not isinstance(template, Ignored)
    assert [n for n, _ in template.blocks[0].attributes] == ["hrcNickName", "sn"]
    acl = parse_assignment(entries[BASE].texts("hrcAclEntry")[0])
    assert not isinstance(acl, Ignored)
    assert acl.user_filter == "(objectClass=hrcMailAccount)"
    assert acl.members == ("*",)


def test_name_carrying_values_are_rewritten() -> None:
    template = _entry(
        f"cn=staff,ou=templates,ou=people,{BASE}",
        objectClass=["fdTemplate"],
        cn=["staff"],
        fdTemplateField=["fdNickName:%givenName%", "sn:%sn%"],
    )
    group = _entry(
        f"cn=mailers,ou=groups,{BASE}",
        objectClass=["groupOfURLs"],
        cn=["mailers"],
        memberURL=[f"ldap:///{BASE}??sub?(objectClass=gosaMailAccount)"],
    )
    out, report = migrate_entries([template, group])
    assert report.errors == []
    entries = _by_dn(out)
    assert entries[template.dn].texts("hrcTemplateField") == ["hrcNickName:%givenName%", "sn:%sn%"]
    assert entries[group.dn].texts("memberURL") == [
        f"ldap:///{BASE}??sub?(objectClass=hrcMailAccount)"
    ]


def test_snapshots_are_migrated_inside() -> None:
    inner = dump_ldif(
        [
            _entry(
                f"uid=ann,{BASE}",
                objectClass=["inetOrgPerson", "fdPersonalInfo"],
                uid=["ann"],
                fdNickName=["annie"],
            )
        ]
    ).encode()
    snapshot = _entry(
        f"gosaSnapshotTimestamp=1700000000-0,ou=snapshots,{BASE}",
        objectClass=["gosaSnapshotObject"],
        gosaSnapshotTimestamp=["1700000000-0"],
        gosaSnapshotDN=[f"uid=ann,{BASE}"],
        gosaSnapshotData=[zlib.compress(inner)],
        fdSnapshotDataSource=["user"],
        fdSnapshotHash=[hashlib.md5(inner, usedforsecurity=False).hexdigest()],
    )
    out, report = migrate_entries([snapshot])
    assert report.errors == []
    (entry,) = out
    assert entry.dn == f"hrcSnapshotTimestamp=1700000000-0,ou=snapshots,{BASE}"
    data = entry.first("hrcSnapshotData")
    assert data is not None
    plain = zlib.decompress(data)
    (restored,) = parse_ldif(plain.decode())
    assert restored.text("hrcNickName") == "annie"
    assert entry.text("hrcSnapshotHash") == hashlib.md5(plain, usedforsecurity=False).hexdigest()


def test_locks_are_dropped_and_unknown_names_are_errors() -> None:
    lock = _entry(
        f"cn=abc,ou=locks,ou=fusiondirectory,{BASE}",
        objectClass=["fdLockEntry"],
        cn=["abc"],
    )
    odd = _entry(
        f"cn=odd,{BASE}",
        objectClass=["device", "fdUnknownThing"],
        cn=["odd"],
        fdMystery=["x"],
    )
    out, report = migrate_entries([lock, odd])
    assert report.dropped_entries == [lock.dn]
    assert [e.dn for e in out] == [odd.dn]
    assert any("fdUnknownThing" in e for e in report.errors)
    assert any("fdMystery" in e for e in report.errors)


def test_invalid_typed_values_are_dropped() -> None:
    task = _entry(
        f"cn=t,ou=tasks,{BASE}",
        objectClass=["fdTasks"],
        cn=["t"],
        fdTasksNextExec=["not a date"],
        fdTasksLastExec=["20240102030405Z"],
    )
    out, report = migrate_entries([task])
    (entry,) = out
    assert entry.get("hrcTasksNextExec") == []
    assert entry.text("hrcTasksLastExec") == "20240102030405Z"
    assert len(report.dropped_values) == 1


def test_ldif_round_trip() -> None:
    text = dump_ldif(
        [
            _entry(
                f"ou=sales,{BASE}",
                objectClass=["organizationalUnit", "gosaDepartment"],
                ou=["sales"],
            )
        ]
    )
    converted, report = migrate_ldif(text)
    assert report.errors == []
    assert "hrcDepartment" in converted
    assert "gosa" not in converted
