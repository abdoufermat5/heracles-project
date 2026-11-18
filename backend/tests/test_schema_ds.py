"""The 389 Directory Server forms of the schema: the export and the online converter."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

from heracles.schema.definitions import ATTRIBUTE_TYPES, OBJECT_CLASSES
from heracles.schema.export import render_ds, render_ldif

ROOT = Path(__file__).resolve().parents[2]


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith(" ") and lines:
            lines[-1] += raw[1:]
        elif raw and not raw.startswith("#"):
            lines.append(raw)
    return lines


def test_ds_export_defines_everything_once() -> None:
    lines = _unfold(render_ds())
    assert lines[:5] == [
        "dn: cn=schema",
        "objectClass: top",
        "objectClass: ldapSubentry",
        "objectClass: subschema",
        "cn: schema",
    ]
    attrs = [line for line in lines if line.startswith("attributeTypes: ")]
    classes = [line for line in lines if line.startswith("objectClasses: ")]
    assert len(attrs) == len(ATTRIBUTE_TYPES) and len(classes) == len(OBJECT_CLASSES)
    assert all(line.endswith(" X-ORIGIN 'heracles' )") for line in attrs + classes)


def test_converter_skips_what_the_server_has(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "ldif2ds", ROOT / "deploy" / "ldap" / "ldif2ds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ldif2ds"] = module
    spec.loader.exec_module(module)
    source = tmp_path / "heracles.ldif"
    source.write_text(render_ldif(), encoding="utf-8")
    out = module.convert([source], {"hrcaclentry", "hrcacl"})
    records = out.strip().split("\n\n")
    assert len(records) == len(ATTRIBUTE_TYPES) + len(OBJECT_CLASSES) - 2
    assert all(r.startswith("dn: cn=schema\nchangetype: modify\nadd: ") for r in records)
    assert "'hrcAclEntry'" not in out and "'hrcAclRoleRDN'" in out
    # attribute types first, so the classes can name them
    first_class = next(i for i, r in enumerate(records) if "add: objectClasses" in r)
    assert all("add: attributeTypes" in r for r in records[:first_class])


def test_converter_expands_object_identifier_macros(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "ldif2ds", ROOT / "deploy" / "ldap" / "ldif2ds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ldif2ds"] = module
    spec.loader.exec_module(module)
    source = tmp_path / "x.ldif"
    source.write_text(
        "dn: cn=x,cn=schema,cn=config\n"
        "olcObjectIdentifier: {0}Base 1.2.3\n"
        "olcObjectIdentifier: {1}Attrs Base:1\n"
        "olcAttributeTypes: {0}( Attrs:7 NAME 'xThing' SYNTAX 1.3.6.1.4.1.1466.115.121.1.15 )\n",
        encoding="utf-8",
    )
    assert "attributeTypes: ( 1.2.3.1.7 NAME 'xThing'" in module.convert([source], set())


def test_converter_decodes_base64_values(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "ldif2ds", ROOT / "deploy" / "ldap" / "ldif2ds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition = "( 1.2.3.4 NAME 'xThing' DESC 'é' SYNTAX 1.3.6.1.4.1.1466.115.121.1.15 )"
    encoded = base64.b64encode(definition.encode()).decode()
    source = tmp_path / "x.ldif"
    source.write_text(f"dn: cn=x,cn=schema,cn=config\nolcAttributeTypes:: {encoded}\n")
    assert f"attributeTypes: {definition}" in module.convert([source], set())
