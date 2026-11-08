"""LDIF (RFC 2849) content records: parser and serializer.

Only content records are supported (no ``changetype``). Used for snapshots and
for seeding the in-memory directory.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Iterator

from heracles.ldap.client import Entry

FOLD_WIDTH = 76


class LdifError(ValueError):
    """Raised on malformed LDIF input."""


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith(" ") and lines and lines[-1] != "":
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_line(line: str) -> tuple[str, bytes]:
    name, sep, rest = line.partition(":")
    if not sep or not name:
        raise LdifError(f"invalid LDIF line: {line!r}")
    if rest.startswith(":"):
        try:
            return name, base64.b64decode(rest[1:].strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise LdifError(f"invalid base64 value for {name!r}") from exc
    if rest.startswith("<"):
        raise LdifError("URL values are not supported")
    return name, rest[1:].encode("utf-8") if rest.startswith(" ") else rest.encode("utf-8")


def parse_ldif(text: str) -> list[Entry]:
    """Parse LDIF text into entries (order preserved)."""
    entries: list[Entry] = []
    current: Entry | None = None
    for line in _unfold(text):
        if line.startswith("#"):
            continue
        if line.strip() == "":
            if current is not None:
                entries.append(current)
                current = None
            continue
        name, value = _parse_line(line)
        lname = name.lower()
        if current is None:
            if lname == "version":
                continue
            if lname != "dn":
                raise LdifError(f"record must start with 'dn:', got {line!r}")
            current = Entry(dn=value.decode("utf-8"))
            continue
        if lname == "dn":
            raise LdifError("'dn:' inside a record; missing blank line?")
        if lname == "changetype":
            raise LdifError("change records are not supported")
        for key in current.attrs:
            if key.lower() == lname:
                current.attrs[key].append(value)
                break
        else:
            current.attrs[name] = [value]
    if current is not None:
        entries.append(current)
    return entries


def _needs_base64(value: bytes) -> bool:
    if not value:
        return False
    if value[0:1] in (b" ", b":", b"<") or value.endswith(b" "):
        return True
    return any(b in (0, 10, 13) or b > 127 for b in value)


def _fold(line: str, width: int = FOLD_WIDTH) -> str:
    """Wrap ``line`` after ``width`` columns (``0`` disables wrapping)."""
    if width <= 0 or len(line) <= width:
        return line
    parts = [line[:width]]
    rest = line[width:]
    while rest:
        parts.append(" " + rest[: width - 1])
        rest = rest[width - 1 :]
    return "\n".join(parts)


def _format(name: str, value: bytes, width: int = FOLD_WIDTH) -> str:
    if _needs_base64(value):
        return _fold(f"{name}:: {base64.b64encode(value).decode('ascii')}", width)
    return _fold(f"{name}: {value.decode('ascii')}", width)


def dump_entry(entry: Entry, *, wrap: int = FOLD_WIDTH) -> str:
    """Serialize one entry (no trailing blank line); ``wrap`` 0 disables line folding."""
    lines = [_format("dn", entry.dn.encode("utf-8"), wrap)]
    for name, values in entry.attrs.items():
        lines.extend(_format(name, v, wrap) for v in values)
    return "\n".join(lines) + "\n"


def dump_ldif(entries: Iterable[Entry], *, wrap: int = FOLD_WIDTH) -> str:
    """Serialize entries, separated by blank lines."""
    return "\n".join(dump_entry(e, wrap=wrap) for e in entries)


def iter_ldif(entries: Iterable[Entry], *, wrap: int = FOLD_WIDTH) -> Iterator[str]:
    """Serialize entries lazily: one chunk per entry, blank-line separated (for streaming)."""
    first = True
    for entry in entries:
        chunk = dump_entry(entry, wrap=wrap)
        yield chunk if first else "\n" + chunk
        first = False
