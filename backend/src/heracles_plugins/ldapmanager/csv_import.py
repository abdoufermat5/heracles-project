"""CSV import: parsing, value coercion and creation through the normal object path."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from heracles.attributes import AnyAttribute
from heracles.objects import TypeInfo
from heracles.objects.model import Tab

MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024
#: Separator of the values of a multi-valued attribute inside one CSV cell.
MULTI_SEPARATOR = "|"
#: Kinds that cannot be filled from a text cell.
UNSUPPORTED_KINDS = frozenset({"file", "image", "display", "composite"})
SEPARATORS = {",": ",", ";": ";", "tab": "\t", "\t": "\t", "|": "|"}
_TRUE = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE = frozenset({"0", "false", "no", "off", "n", "f", ""})


class CsvError(ValueError):
    """Malformed CSV input or mapping."""


@dataclass(frozen=True, slots=True)
class Field:
    """An attribute that a CSV column (or a fixed value) can fill."""

    tab: str
    attribute: AnyAttribute

    @property
    def key(self) -> str:
        return f"{self.tab}.{self.attribute.name}"


@dataclass(slots=True)
class ParsedCsv:
    columns: list[str]
    rows: list[list[str]]
    #: Physical line number (1-based) of the last line of each row.
    lines: list[int] = field(default_factory=lambda: [])


def parse_csv(text: str, separator: str, *, has_header: bool) -> ParsedCsv:
    """Parse ``text``; the first record is the header when ``has_header``."""
    delimiter = SEPARATORS.get(separator)
    if delimiter is None:
        raise CsvError("Unsupported separator")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CsvError("The file is too large")
    reader = csv.reader(io.StringIO(text.lstrip("﻿"), newline=""), delimiter=delimiter)
    columns: list[str] = []
    rows: list[list[str]] = []
    lines: list[int] = []
    try:
        for record in reader:
            if not any(cell.strip() for cell in record):
                continue
            if has_header and not columns and not rows:
                columns = [cell.strip() for cell in record]
                continue
            rows.append([cell.strip() for cell in record])
            lines.append(reader.line_num)
            if len(rows) > MAX_ROWS:
                raise CsvError(f"At most {MAX_ROWS} lines can be imported at once")
    except csv.Error as exc:
        raise CsvError(f"Malformed CSV: {exc}") from exc
    width = max([len(columns), *[len(r) for r in rows]], default=0)
    if not has_header:
        columns = [f"#{i + 1}" for i in range(width)]
    elif len(columns) < width:
        columns += [f"#{i + 1}" for i in range(len(columns), width)]
    return ParsedCsv(columns, rows, lines)


def importable_fields(info: TypeInfo) -> list[Field]:
    """Attributes that can be filled from text."""
    out: list[Field] = []
    for tab in info.tabs:
        for attr in tab.attributes():
            if attr.readonly or attr.kind in UNSUPPORTED_KINDS:
                continue
            if not attr.stored and attr.kind != "department":
                continue
            if attr.kind == "list" and _item_kind(attr) in UNSUPPORTED_KINDS:
                continue
            out.append(Field(tab.name, attr))
    return out


def field_by_key(info: TypeInfo, key: str) -> Field | None:
    tab_name, _, attr_name = key.partition(".")
    for item in importable_fields(info):
        if item.tab == tab_name and item.attribute.name == attr_name:
            return item
    return None


def template_fields_only(
    fields: Sequence[Field], wanted: Mapping[str, Sequence[str]]
) -> list[Field]:
    """The fields a template asks for (``tab -> attribute names``)."""
    return [f for f in fields if f.attribute.name in set(wanted.get(f.tab, ()))]


def _item_kind(attr: AnyAttribute) -> str:
    item: Any = getattr(attr, "item", None)
    return str(item.kind) if item is not None else ""


def coerce(attr: AnyAttribute, text: str) -> object:
    """JSON value for a cell: ``None`` for an empty cell, else typed by the attribute kind."""
    text = text.strip()
    if text == "":
        return None
    if attr.multivalued:
        item: Any = getattr(attr, "item", None)
        parts = [p.strip() for p in text.split(MULTI_SEPARATOR) if p.strip()]
        if item is None:
            return parts
        return [_scalar(cast("AnyAttribute", item), p) for p in parts]
    return _scalar(attr, text)


def _scalar(attr: AnyAttribute, text: str) -> object:
    kind = str(attr.kind)
    try:
        if kind == "int":
            return int(text)
        if kind == "float":
            return float(text)
    except ValueError:
        raise CsvError(f"{attr.name}: not a number") from None
    if kind == "boolean":
        lowered = text.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise CsvError(f"{attr.name}: not a boolean")
    return text


def row_values(
    info: TypeInfo,
    row: Sequence[str],
    mapping: Sequence[tuple[int, Field]],
    fixed: Mapping[str, Field],
    fixed_values: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """``{tab: {attr: json value}}`` of one row: fixed values first, mapped cells over them."""
    out: dict[str, dict[str, Any]] = {}
    for key, target in fixed.items():
        value = coerce(target.attribute, fixed_values[key])
        if value is not None:
            out.setdefault(target.tab, {})[target.attribute.name] = value
    for column, target in mapping:
        cell = row[column] if column < len(row) else ""
        value = coerce(target.attribute, cell)
        if value is not None:
            out.setdefault(target.tab, {})[target.attribute.name] = value
    return out


def payload_of(
    info: TypeInfo, values: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Object-service payload: every tab holding a value is activated."""
    tabs: dict[str, type[Tab]] = {t.name: t for t in info.tabs}
    return {
        name: {"active": True, "values": dict(vals)}
        for name, vals in values.items()
        if name in tabs
    }
