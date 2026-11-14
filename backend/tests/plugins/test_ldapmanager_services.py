"""LDIF import planning and CSV parsing / coercion, on the in-memory directory."""

from __future__ import annotations

import pytest

from heracles import demo
from heracles.api.errors import ApiError
from heracles.ldap.client import Entry, Scope
from heracles.ldap.ldif import parse_ldif
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.ldapmanager import csv_import as csvlib
from heracles_plugins.ldapmanager import ldif_import as importer
from heracles_plugins.ldapmanager.router import check_export_size

BASE = demo.BASE


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def run(
    directory: MemoryDirectory,
    text: str,
    *,
    overwrite: bool = False,
    remove_missing: bool = False,
    apply: bool = True,
    allowed: bool = True,
) -> list[importer.EntryResult]:
    return importer.run_import(
        directory,
        parse_ldif(text),
        importer.ImportOptions(overwrite, remove_missing),
        allowed=lambda _dn: allowed,
        apply=apply,
    )


NEW = f"""\
dn: ou=new,{BASE}
objectClass: organizationalUnit
ou: new

dn: cn=child,ou=new,{BASE}
objectClass: organizationalRole
cn: child
description: first
"""


def test_adds_in_order_and_dry_run_writes_nothing(directory: MemoryDirectory) -> None:
    plan = run(directory, NEW, apply=False)
    assert [r.action for r in plan] == ["add", "add"]
    assert directory.get(f"ou=new,{BASE}") is None
    done = run(directory, NEW)
    assert [r.action for r in done] == ["add", "add"]
    child = directory.get(f"cn=child,ou=new,{BASE}")
    assert child is not None and child.text("description") == "first"
    assert importer.summarize(done)["add"] == 2


def test_missing_parent_is_reported_and_does_not_stop_the_run(directory: MemoryDirectory) -> None:
    text = f"""\
dn: cn=orphan,ou=ghost,{BASE}
objectClass: organizationalRole
cn: orphan

dn: ou=ok,{BASE}
objectClass: organizationalUnit
ou: ok
"""
    results = run(directory, text)
    assert [r.action for r in results] == ["error", "add"]
    assert results[0].error == "The parent entry does not exist"
    assert directory.get(f"ou=ok,{BASE}") is not None


def test_existing_entry_without_overwrite(directory: MemoryDirectory) -> None:
    text = f"dn: ou=paris,{BASE}\nobjectClass: organizationalUnit\nou: paris\n"
    [result] = run(directory, text)
    assert result.action == "exists" and result.error


def test_overwrite_replaces_and_remove_missing_deletes(directory: MemoryDirectory) -> None:
    dn = f"ou=paris,{BASE}"
    text = (
        f"dn: {dn}\nobjectClass: organizationalUnit\n"
        "objectClass: hrcDepartment\nou: paris\nl: Paris\n"
    )
    [kept] = run(directory, text, overwrite=True)
    entry = directory.get(dn)
    assert entry is not None
    assert kept.action == "modify" and kept.changes == ["l"]
    assert entry.text("description") == "Paris office"  # not in the LDIF, kept
    [removed] = run(directory, text, overwrite=True, remove_missing=True)
    entry = directory.get(dn)
    assert entry is not None
    assert removed.action == "modify" and removed.changes == ["description"]
    assert entry.text("description") is None
    [again] = run(directory, text, overwrite=True, remove_missing=True)
    assert again.action == "unchanged"


def test_not_allowed_entries_are_rejected(directory: MemoryDirectory) -> None:
    [result] = run(directory, NEW.split("\n\n")[0], allowed=False)
    assert result.action == "error" and "not allowed" in (result.error or "")
    assert directory.get(f"ou=new,{BASE}") is None


def test_duplicates_and_missing_object_class(directory: MemoryDirectory) -> None:
    first = NEW.split("\n\n")[0]
    results = run(directory, first + "\n\n" + first, apply=False)
    assert [r.action for r in results] == ["add", "error"]
    assert results[1].error == "Duplicate entry in the file"
    applied = run(directory, first + "\n\n" + first)
    assert [r.action for r in applied] == ["add", "exists"]
    [bare] = run(directory, f"dn: ou=bare,{BASE}\nou: bare\n")
    assert bare.error == "The entry has no objectClass"


def test_privileged_attributes_are_recognised_with_attribute_options() -> None:
    plain = parse_ldif(f"dn: uid=x,{BASE}\nobjectClass: top\nuserPassword: x\n")[0]
    tagged = parse_ldif(f"dn: uid=x,{BASE}\nobjectClass: top\nuserPassword;binary: x\n")[0]
    assert importer.privileged_content(plain) is not None
    assert importer.privileged_content(tagged) is not None
    harmless = parse_ldif(f"dn: uid=x,{BASE}\nobjectClass: top\ndescription;lang-fr: x\n")[0]
    assert importer.privileged_content(harmless) is None


def test_export_hides_secrets_that_no_tab_describes() -> None:
    from heracles_plugins.ldapmanager.access import Access

    # e.g. the SMB hashes of an entry whose plugin is switched off: no tab knows them
    assert not Access._attribute_visible("dn", "sambaNTPassword", [])  # pyright: ignore[reportPrivateUsage]
    assert not Access._attribute_visible("dn", "krbPrincipalKey", [])  # pyright: ignore[reportPrivateUsage]
    assert Access._attribute_visible("dn", "objectClass", [])  # pyright: ignore[reportPrivateUsage]


# -- CSV ----------------------------------------------------------------------------------------
def test_parse_csv_with_and_without_header() -> None:
    parsed = csvlib.parse_csv('a,b\n1,2\n\n3,"x,y"\n', ",", has_header=True)
    assert parsed.columns == ["a", "b"]
    assert parsed.rows == [["1", "2"], ["3", "x,y"]]
    assert parsed.lines == [2, 4]
    bare = csvlib.parse_csv("1;2;3\n", ";", has_header=False)
    assert bare.columns == ["#1", "#2", "#3"] and bare.rows == [["1", "2", "3"]]
    tabbed = csvlib.parse_csv("﻿a\tb\n1\t2", "tab", has_header=True)
    assert tabbed.columns == ["a", "b"]


def test_parse_csv_errors() -> None:
    with pytest.raises(csvlib.CsvError):
        csvlib.parse_csv("a", "x", has_header=True)
    with pytest.raises(csvlib.CsvError, match="At most"):
        csvlib.parse_csv("a\n" + "1\n" * (csvlib.MAX_ROWS + 1), ",", has_header=True)


def test_fields_and_coercion() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    info = registry.get("user")
    fields = {f.key: f for f in csvlib.importable_fields(info)}
    assert "main.sn" in fields and "main.userPassword" in fields
    assert csvlib.field_by_key(info, "main.sn") == fields["main.sn"]
    assert csvlib.field_by_key(info, "main.nope") is None
    sn = fields["main.sn"].attribute
    assert csvlib.coerce(sn, " Doe ") == "Doe" and csvlib.coerce(sn, "  ") is None
    group = registry.get("group")
    member = next(f for f in csvlib.importable_fields(group) if f.attribute.name == "member")
    assert csvlib.coerce(member.attribute, "a|b| c") == ["a", "b", "c"]


def test_scalar_coercion_of_numbers_and_booleans() -> None:
    from heracles.attributes import BooleanAttr, IntAttr

    number = IntAttr("n", "N")
    assert csvlib.coerce(number, "42") == 42
    with pytest.raises(csvlib.CsvError):
        csvlib.coerce(number, "abc")
    flag = BooleanAttr("b", "B")
    assert csvlib.coerce(flag, "Yes") is True and csvlib.coerce(flag, "0") is False
    with pytest.raises(csvlib.CsvError):
        csvlib.coerce(flag, "maybe")


def test_row_values_and_payload() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    info = registry.get("user")
    fields = {f.key: f for f in csvlib.importable_fields(info)}
    values = csvlib.row_values(
        info,
        ["Doe", "John"],
        [(0, fields["main.sn"]), (1, fields["main.givenName"])],
        {"main.description": fields["main.description"]},
        {"main.description": "imported"},
    )
    assert values == {"main": {"description": "imported", "sn": "Doe", "givenName": "John"}}
    payload = csvlib.payload_of(info, {**values, "ghost": {"x": 1}})
    assert payload == {"main": {"active": True, "values": values["main"]}}
    assert csvlib.template_fields_only(list(fields.values()), {"main": ["sn"]}) == [
        fields["main.sn"]
    ]


def test_entry_helper_is_importable() -> None:
    assert Entry("cn=x").dn == "cn=x"


def test_export_size_check_refuses_too_many_entries(directory: MemoryDirectory) -> None:
    with pytest.raises(ApiError) as refused:
        check_export_size(directory, BASE, "(objectClass=*)", Scope.SUBTREE, 2)
    assert refused.value.status == 422
    assert refused.value.fields == {"filter": "too many entries"}

    # The whole demo subtree fits under a wide cap, and an exact fit is allowed.
    total = len(list(directory.search(BASE, "(objectClass=*)", Scope.SUBTREE)))
    check_export_size(directory, BASE, "(objectClass=*)", Scope.SUBTREE, total)
    with pytest.raises(ApiError):
        check_export_size(directory, BASE, "(objectClass=*)", Scope.SUBTREE, total - 1)
