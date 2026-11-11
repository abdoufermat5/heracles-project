#!/usr/bin/env python3
"""Convert OpenLDAP ``.schema`` files to ``cn=config`` LDIF schema entries.

    python3 deploy/ldap/schema2ldif.py path/to/name.schema [...] -o deploy/ldap/schema

Each ``<name>.schema`` becomes ``<prefix><name>.ldif`` (prefix from ``--prefix``, to
control the load order) containing one ``olcSchemaConfig`` entry.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_KEYWORDS = {
    "attributetype": "olcAttributeTypes",
    "objectclass": "olcObjectClasses",
    "objectidentifier": "olcObjectIdentifier",
    "ldapsyntax": "olcLdapSyntaxes",
}


def _definitions(text: str) -> list[tuple[str, str]]:
    """``(keyword, definition)`` pairs; definitions are balanced ``( ... )`` blocks."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    src = "\n".join(lines)
    out: list[tuple[str, str]] = []
    pattern = re.compile(r"\b(attributetype|objectclass|objectidentifier|ldapsyntax)\b", re.I)
    pos = 0
    while (m := pattern.search(src, pos)) is not None:
        keyword = m.group(1).lower()
        i = m.end()
        while i < len(src) and src[i].isspace():
            i += 1
        if keyword == "objectidentifier":
            end = src.find("\n", i)
            end = len(src) if end == -1 else end
            out.append((keyword, " ".join(src[i:end].split())))
            pos = end
            continue
        if i >= len(src) or src[i] != "(":
            pos = i
            continue
        depth, j, quoted = 0, i, False
        while j < len(src):
            ch = src[j]
            if ch == "'":
                quoted = not quoted
            elif not quoted and ch == "(":
                depth += 1
            elif not quoted and ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((keyword, " ".join(src[i : j + 1].split())))
        pos = j + 1
    return out


def convert(schema: Path) -> str:
    name = schema.stem
    lines = [
        f"dn: cn={name},cn=schema,cn=config",
        "objectClass: olcSchemaConfig",
        f"cn: {name}",
    ]
    for keyword, definition in _definitions(schema.read_text(encoding="utf-8")):
        lines.append(f"{_KEYWORDS[keyword]}: {definition}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("schemas", nargs="+", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--prefix", default="", help="file name prefix (load order)")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for schema in args.schemas:
        target = args.output / f"{args.prefix}{schema.stem}.ldif"
        target.write_text(convert(schema), encoding="utf-8")
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
