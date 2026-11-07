"""RFC 4515 LDAP search filter: parser, AST, evaluator and value escaping.

The evaluator works on :class:`heracles.ldap.client.Entry` and is used by the
in-memory directory. Attribute names and string values are compared
case-insensitively. Approximate match (``~=``) is treated as equality.
"""

from __future__ import annotations

from dataclasses import dataclass

from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry


class FilterError(ValueError):
    """Raised when a filter string cannot be parsed."""


@dataclass(frozen=True, slots=True)
class And:
    """Conjunction ``(&...)``."""

    children: tuple[Filter, ...]


@dataclass(frozen=True, slots=True)
class Or:
    """Disjunction ``(|...)``."""

    children: tuple[Filter, ...]


@dataclass(frozen=True, slots=True)
class Not:
    """Negation ``(!...)``."""

    child: Filter


@dataclass(frozen=True, slots=True)
class Equal:
    """Equality (and approximate) match ``(attr=value)``."""

    attr: str
    value: str


@dataclass(frozen=True, slots=True)
class Present:
    """Presence ``(attr=*)``."""

    attr: str


@dataclass(frozen=True, slots=True)
class Substring:
    """Substring match ``(attr=initial*any*...*final)``."""

    attr: str
    initial: str | None
    any: tuple[str, ...]
    final: str | None


@dataclass(frozen=True, slots=True)
class GreaterOrEqual:
    """``(attr>=value)``."""

    attr: str
    value: str


@dataclass(frozen=True, slots=True)
class LessOrEqual:
    """``(attr<=value)``."""

    attr: str
    value: str


Filter = And | Or | Not | Equal | Present | Substring | GreaterOrEqual | LessOrEqual

_SPECIAL = {"\\": "\\5c", "*": "\\2a", "(": "\\28", ")": "\\29", "\x00": "\\00"}
_HEX = set("0123456789abcdefABCDEF")


def escape_filter_value(value: str) -> str:
    """Escape ``value`` for safe inclusion in a filter (RFC 4515)."""
    return "".join(_SPECIAL.get(ch, ch) for ch in value)


def _unescape(raw: str) -> str:
    """Decode ``\\XX`` hex escapes (UTF-8 byte sequences) in a value fragment."""
    if "\\" not in raw:
        return raw
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\":
            pair = raw[i + 1 : i + 3]
            if len(pair) != 2 or not all(c in _HEX for c in pair):
                raise FilterError(f"invalid escape in filter value: {raw!r}")
            out.append(int(pair, 16))
            i += 3
        else:
            out.extend(ch.encode("utf-8"))
            i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FilterError(f"escaped value is not valid UTF-8: {raw!r}") from exc


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def error(self, msg: str) -> FilterError:
        return FilterError(f"{msg} at position {self.i} in filter {self.s!r}")

    def parse(self) -> Filter:
        self._skip_ws()
        if self.i < len(self.s) and self.s[self.i] != "(":
            # Tolerate a bare simple item such as ``cn=foo``.
            node = self._item(self.s.strip())
            self.i = len(self.s)
            return node
        node = self._filter()
        self._skip_ws()
        if self.i != len(self.s):
            raise self.error("trailing characters")
        return node

    def _skip_ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def _filter(self) -> Filter:
        self._skip_ws()
        if self.i >= len(self.s) or self.s[self.i] != "(":
            raise self.error("expected '('")
        self.i += 1
        self._skip_ws()
        if self.i >= len(self.s):
            raise self.error("unexpected end of filter")
        ch = self.s[self.i]
        node: Filter
        if ch in "&|":
            self.i += 1
            children = self._filter_list()
            node = And(children) if ch == "&" else Or(children)
        elif ch == "!":
            self.i += 1
            node = Not(self._filter())
        else:
            end = self._item_end()
            node = self._item(self.s[self.i : end])
            self.i = end
        self._skip_ws()
        if self.i >= len(self.s) or self.s[self.i] != ")":
            raise self.error("expected ')'")
        self.i += 1
        return node

    def _filter_list(self) -> tuple[Filter, ...]:
        items: list[Filter] = []
        self._skip_ws()
        while self.i < len(self.s) and self.s[self.i] == "(":
            items.append(self._filter())
            self._skip_ws()
        if not items:
            raise self.error("empty filter list")
        return tuple(items)

    def _item_end(self) -> int:
        j = self.i
        while j < len(self.s) and self.s[j] != ")":
            if self.s[j] == "(":
                raise self.error("unescaped '(' in filter value")
            j += 1
        return j

    def _item(self, text: str) -> Filter:
        eq = text.find("=")
        if eq <= 0:
            raise self.error("missing filter operator")
        op = "="
        attr_end = eq
        if text[eq - 1] in "<>~" and eq >= 2:
            op = text[eq - 1] + "="
            attr_end = eq - 1
        attr = text[:attr_end].strip()
        raw = text[eq + 1 :]
        if not attr or ":" in attr:
            raise self.error("invalid attribute or unsupported extensible match")
        if op == ">=":
            return GreaterOrEqual(attr, _unescape(raw))
        if op == "<=":
            return LessOrEqual(attr, _unescape(raw))
        if "*" not in raw or op == "~=":
            return Equal(attr, _unescape(raw))
        if raw == "*":
            return Present(attr)
        parts = raw.split("*")
        initial = _unescape(parts[0]) if parts[0] else None
        final = _unescape(parts[-1]) if parts[-1] else None
        middle = tuple(_unescape(p) for p in parts[1:-1] if p)
        return Substring(attr, initial, middle, final)


def parse_filter(text: str) -> Filter:
    """Parse an RFC 4515 filter string into an AST."""
    return _Parser(text).parse()


def _fold(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").casefold()


def _values_equal(have: bytes, want: str) -> bool:
    a = _fold(have)
    b = want.casefold()
    if a == b:
        return True
    if "=" in a and "=" in b and "," in a + b:
        return dnlib.normalize(a) == dnlib.normalize(b)
    return a.strip() == b.strip()


def _ordering(have: bytes, want: str) -> int:
    a = have.decode("utf-8", errors="replace")
    try:
        ia, ib = int(a), int(want)
    except ValueError:
        fa, fb = a.casefold(), want.casefold()
        return (fa > fb) - (fa < fb)
    return (ia > ib) - (ia < ib)


def _substring(have: bytes, node: Substring) -> bool:
    text = _fold(have)
    pos = 0
    if node.initial is not None:
        init = node.initial.casefold()
        if not text.startswith(init):
            return False
        pos = len(init)
    for part in node.any:
        idx = text.find(part.casefold(), pos)
        if idx < 0:
            return False
        pos = idx + len(part)
    if node.final is not None:
        fin = node.final.casefold()
        return text.endswith(fin) and len(text) - len(fin) >= pos
    return True


def matches(entry: Entry, flt: Filter | str) -> bool:
    """Evaluate ``flt`` (AST or filter string) against ``entry``."""
    node = parse_filter(flt) if isinstance(flt, str) else flt
    return _eval(entry, node)


def _eval(entry: Entry, node: Filter) -> bool:
    match node:
        case And(children):
            return all(_eval(entry, c) for c in children)
        case Or(children):
            return any(_eval(entry, c) for c in children)
        case Not(child):
            return not _eval(entry, child)
        case Present(attr):
            return bool(entry.get(attr))
        case Equal(attr, value):
            return any(_values_equal(v, value) for v in entry.get(attr))
        case Substring():
            return any(_substring(v, node) for v in entry.get(node.attr))
        case GreaterOrEqual(attr, value):
            return any(_ordering(v, value) >= 0 for v in entry.get(attr))
        case LessOrEqual(attr, value):
            return any(_ordering(v, value) <= 0 for v in entry.get(attr))
