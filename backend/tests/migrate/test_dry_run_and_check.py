"""R2: the dry-run report and the post-migration checks, on a synthetic legacy directory."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from heracles.cli.main import main
from heracles.ldap.client import Entry
from heracles.ldap.ldif import dump_ldif
from heracles.migrate import check
from heracles.migrate.directory import migrate_entries, migrate_ldif

BASE = "dc=example,dc=org"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _entry(dn: str, **attrs: list[str]) -> Entry:
    return Entry(dn=dn, attrs={k: [v.encode() for v in vs] for k, vs in attrs.items()})


def legacy_directory() -> list[Entry]:
    """A small directory in the legacy layout: departments, people, a group, ACL roles."""
    role = f"cn=editors,ou=aclroles,{BASE}"
    return [
        _entry(
            BASE,
            objectClass=["dcObject", "organization", "gosaAcl"],
            dc=["example"],
            o=["Example"],
            gosaAclEntry=[f"0:subtree:{_b64(role)}:{_b64(f'uid=ann,ou=people,{BASE}')}", "garbage"],
        ),
        _entry(f"ou=people,{BASE}", objectClass=["organizationalUnit"], ou=["people"]),
        _entry(f"ou=groups,{BASE}", objectClass=["organizationalUnit"], ou=["groups"]),
        _entry(f"ou=aclroles,{BASE}", objectClass=["organizationalUnit"], ou=["aclroles"]),
        _entry(
            f"ou=sales,{BASE}", objectClass=["organizationalUnit", "gosaDepartment"], ou=["sales"]
        ),
        _entry(
            role,
            objectClass=["top", "gosaRole"],
            cn=["editors"],
            gosaAclTemplate=["0:user/user;rw"],
        ),
        _entry(
            f"uid=ann,ou=people,{BASE}",
            objectClass=["inetOrgPerson"],
            uid=["ann"],
            cn=["Ann"],
            sn=["Lee"],
            userPassword=["{CLEARTEXT}ann-secret"],
        ),
        _entry(
            f"uid=bob,ou=people,{BASE}",
            objectClass=["inetOrgPerson", "fdMysteryAccount"],
            uid=["bob"],
            cn=["Bob"],
            sn=["Ray"],
            fdMysteryThing=["x"],
            userPassword=["{CLEARTEXT}bob-secret"],
        ),
        _entry(
            f"uid=cy,ou=people,{BASE}",
            objectClass=["inetOrgPerson"],
            uid=["cy"],
            cn=["Cy"],
            sn=["Ito"],
            fdMysteryThing=["y"],
        ),
        _entry(
            f"cn=devs,ou=groups,{BASE}",
            objectClass=["groupOfNames"],
            cn=["devs"],
            member=[f"uid=ann,ou=people,{BASE}"],
        ),
    ]


def test_report_counts_and_groups_what_is_left() -> None:
    _out, report = migrate_entries(legacy_directory())
    counts = (report.entries_total, report.entries_converted, report.entries_untouched)
    assert counts == (10, 3, 7) and not report.dropped_entries
    unknown = {(u.kind, u.name): u for u in report.unknown.values()}
    attr = unknown[("attribute", "fdMysteryThing")]
    assert attr.count == 2 and attr.samples == [
        f"uid=bob,ou=people,{BASE}",
        f"uid=cy,ou=people,{BASE}",
    ]
    assert unknown[("objectClass", "fdMysteryAccount")].count == 1
    assert len(report.acl_errors) == 1 and "garbage" in report.acl_errors[0]
    assert report.clean is False
    doc = json.loads(json.dumps(report.to_json()))
    assert doc["entries"] == {"total": 10, "converted": 3, "untouched": 7, "dropped": 0}
    text = report.summary()
    assert "attribute fdMysteryThing: 2" in text and "result: NOT clean" in text


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "old.ldif"
    source.write_text(dump_ldif(legacy_directory()), encoding="utf-8")
    assert main(["migrate-directory", str(source), "--dry-run", "--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["entries"]["total"] == 10 and doc["clean"] is False
    assert list(tmp_path.iterdir()) == [source]
    clean = [e for e in legacy_directory() if "bob" not in e.dn and "cy" not in e.dn]
    clean[0].attrs["gosaAclEntry"] = clean[0].attrs["gosaAclEntry"][:1]
    source.write_text(dump_ldif(clean), encoding="utf-8")
    assert main(["migrate-directory", str(source), "--dry-run"]) == 0
    assert "result: clean" in capsys.readouterr().out


def converted() -> str:
    entries = [e for e in legacy_directory() if "bob" not in e.dn and "cy" not in e.dn]
    entries[0].attrs["gosaAclEntry"] = entries[0].attrs["gosaAclEntry"][:1]
    text, report = migrate_ldif(dump_ldif(entries))
    assert report.clean, report.errors
    return text


def test_checks_on_the_converted_tree(tmp_path: Path) -> None:
    directory = check.load_ldif(converted())
    ann, devs = f"uid=ann,ou=people,{BASE}", f"cn=devs,ou=groups,{BASE}"
    assert (
        check.rights_of(directory, ann, f"uid=cy,ou=people,{BASE}", "user/user").canonical() == "rw"
    )
    results = check.compare_rights(
        directory, [["subject", "object", "key", "expected"], [ann, devs, "user/user", "wr"]]
    )
    assert results[0]["ok"] is True
    wrong = check.compare_rights(directory, [[ann, devs, "user/user", "rwcd"]])
    assert wrong[0]["ok"] is False and wrong[0]["actual"] == "rw"
    logins = check.logins(directory, [["ann", "ann-secret"], ["ann", "nope"], ["zed", "x"]])
    assert [x["ok"] for x in logins] == [True, False, False]


def test_migrate_check_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ldif = tmp_path / "new.ldif"
    ldif.write_text(converted(), encoding="utf-8")
    ann = f"uid=ann,ou=people,{BASE}"
    triples = tmp_path / "triples.csv"
    triples.write_text(f'subject,object,key\n"{ann}","{BASE}",user/user\n', encoding="utf-8")
    expected = tmp_path / "expected.csv"
    assert (
        main(["migrate-check", "--ldif", str(ldif), "--export-rights", str(triples), str(expected)])
        == 0
    )
    assert expected.read_text(encoding="utf-8").splitlines()[1].endswith(",rw")
    capsys.readouterr()
    logins = tmp_path / "logins.csv"
    logins.write_text("ann,ann-secret\n", encoding="utf-8")
    argv = [
        "migrate-check",
        "--ldif",
        str(ldif),
        "--rights",
        str(expected),
        "--logins",
        str(logins),
    ]
    code = main([*argv, "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["rights"][0]["ok"] is True and doc["logins"][0]["ok"] is True
    assert code == (0 if doc["ok"] else 1)
