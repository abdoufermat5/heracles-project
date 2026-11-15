#!/usr/bin/env python3
"""Turn ``cn=config`` schema LDIF files into one online schema update for 389 Directory Server.

    python3 deploy/ldap/ldif2ds.py deploy/ldap/schema/*.ldif --skip existing-names.txt > add.ldif
    ldapmodify -H ldap://... -D "cn=Directory Manager" -w ... -f add.ldif

Reads the ``olcAttributeTypes`` and ``olcObjectClasses`` values (``{N}`` order prefixes
dropped, ``olcObjectIdentifier`` macros expanded) and writes ``dn: cn=schema`` modify
records adding them as ``attributeTypes`` / ``objectClasses``. ``--skip`` names a file of
definition names (one per line, any case) the server already has: those are left out, so the
standard schemas the server ships are not defined twice. Attribute types come before object
classes, in file order.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_INDEX = re.compile(r"^\{\d+\}")
_NAMES = re.compile(r"NAME\s+(?:'([^']+)'|\(\s*([^)]*)\))")


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith(" ") and lines:
            lines[-1] += raw[1:]
        elif raw and not raw.startswith("#"):
            lines.append(raw)
    return lines


def names(definition: str) -> list[str]:
    match = _NAMES.search(definition)
    if not match:
        return []
    if match.group(1):
        return [match.group(1)]
    return re.findall(r"'([^']+)'", match.group(2) or "")


def expand(definition: str, macros: dict[str, str]) -> str:
    def oid(token: str) -> str:
        head, _, tail = token.partition(":")
        if head in macros:
            return macros[head] + ("." + tail if tail else "")
        return token

    body = definition.strip()
    if body.startswith("("):
        first = body[1:].split(None, 1)
        if first:
            rest = first[1] if len(first) > 1 else ""
            body = "( " + oid(first[0]) + " " + rest
    return body


def convert(paths: list[Path], skip: set[str]) -> str:
    attrs: list[str] = []
    classes: list[str] = []
    for path in paths:
        macros: dict[str, str] = {}
        for line in unfold(path.read_text(encoding="utf-8")):
            key, _, value = line.partition(":")
            value = _INDEX.sub("", value.strip())
            lowered = key.strip().lower()
            if lowered == "olcobjectidentifier":
                name, _, target = value.partition(" ")
                head, _, tail = target.strip().partition(":")
                base = macros.get(head, head)
                macros[name] = base + ("." + tail if tail else "")
            elif lowered in ("olcattributetypes", "olcobjectclasses"):
                definition = expand(value, macros)
                if any(n.lower() in skip for n in names(definition)):
                    continue
                (attrs if lowered == "olcattributetypes" else classes).append(definition)
    out: list[str] = []
    for kind, values in (("attributeTypes", attrs), ("objectClasses", classes)):
        for value in values:
            out += ["dn: cn=schema", "changetype: modify", f"add: {kind}", f"{kind}: {value}", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--skip", type=Path, help="file of names the server already defines")
    args = parser.parse_args(argv)
    skip: set[str] = set()
    if args.skip:
        skip = {
            n.strip().lower() for n in args.skip.read_text(encoding="utf-8").split() if n.strip()
        }
    sys.stdout.write(convert(args.files, skip))
    return 0


if __name__ == "__main__":
    sys.exit(main())
