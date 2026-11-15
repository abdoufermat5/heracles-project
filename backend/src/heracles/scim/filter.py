"""SCIM filters (RFC 7644 section 3.4.2.2): parse to an AST, compile to an LDAP filter.

Owner: stream A. Contract (stable, other streams code against it):

* :func:`parse` turns a filter string into a :data:`Filter` AST. Attribute paths are
  returned as written but with the schema URN prefix kept (``urn:...:User:employeeNumber``)
  and sub-attributes joined by a dot (``name.familyName``). Operators are lower-cased.
  Values: JSON literals (string, number, ``true``/``false``, ``null``). Precedence:
  ``not`` > ``and`` > ``or``; parentheses; value paths ``emails[type eq "work"]`` (also
  followed by ``.sub``: ``emails[type eq "work"].value``). Any syntax error is
  ``ScimError(400, ..., INVALID_FILTER)``.
* :func:`to_ldap` compiles an AST with a ``resolve`` callback mapping a SCIM attribute path
  (case-insensitive; the callback receives it lower-cased, URN prefix included when given)
  to an LDAP attribute name, or ``None`` when the path cannot be searched -> 400
  ``invalidFilter``. Values are escaped (RFC 4515). ``eq`` -> ``(a=v)``, ``ne`` ->
  ``(!(a=v))``, ``co`` -> ``(a=*v*)``, ``sw`` -> ``(a=v*)``, ``ew`` -> ``(a=*v)``, ``pr`` ->
  ``(a=*)``, ``gt``/``ge``/``lt``/``le`` -> ``(&(a>=v)(!(a=v)))`` / ``(a>=v)`` /
  ``(&(a<=v)(!(a=v)))`` / ``(a<=v)``. A value path ``attr[sub op v]`` resolves
  ``attr.sub``; boolean values compile as ``TRUE`` / ``FALSE``. :func:`attributes_of`
  lists the LDAP attributes a compiled filter tests (for the caller's read checks).
* :func:`matches` evaluates an AST on one resource dict: used only for PATCH value paths
  (``members[value eq "x"]``), never to filter listings.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from heracles.scim.errors import INVALID_FILTER, ScimError

type Value = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Compare:
    """``path op value`` (``value`` is ``None`` for ``pr``)."""

    path: str
    op: str
    value: Value = None


@dataclass(frozen=True, slots=True)
class And:
    left: Filter
    right: Filter


@dataclass(frozen=True, slots=True)
class Or:
    left: Filter
    right: Filter


@dataclass(frozen=True, slots=True)
class Not:
    inner: Filter


@dataclass(frozen=True, slots=True)
class ValuePath:
    """``attr[filter]``: ``filter`` paths are relative to the multi-valued ``attr``."""

    path: str
    filter: Filter


type Filter = Compare | And | Or | Not | ValuePath

#: Comparison operators of RFC 7644 table 3.
OPERATORS = frozenset({"eq", "ne", "co", "sw", "ew", "gt", "ge", "lt", "le", "pr"})


_VERSION = re.compile(r"\d+(\.\d+)*")
_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_PATH = re.compile(r"[A-Za-z][A-Za-z0-9_$:.\-]*")
_ATTR = re.compile(r"[A-Za-z][A-Za-z0-9_$\-]*")


def _invalid(detail: str) -> ScimError:
    return ScimError(400, detail, INVALID_FILTER)


def split_path(path: str) -> tuple[str | None, str]:
    """Split ``urn:...:User:attr.sub`` into ``(urn, "attr.sub")``.

    A path that is only a schema URN (its last segment is a version such as ``2.0``) gives
    ``(path, "")``. Paths without a URN prefix give ``(None, path)``.
    """
    if not path.lower().startswith("urn:"):
        return None, path
    left, _, right = path.rpartition(":")
    if not left or _VERSION.fullmatch(right) or _VERSION.fullmatch(left.rpartition(":")[2]):
        return path, ""
    return left, right


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: str  # "(" ")" "[" "]" "str" "num" "word"
    text: str
    pos: int
    value: Value = None


def _tokenize(text: str) -> list[_Tok]:
    out: list[_Tok] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()[]":
            out.append(_Tok(c, c, i))
            i += 1
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise _invalid(f"unterminated string starting at position {i}")
            raw = text[i : j + 1]
            try:
                parsed = json.loads(raw)
            except ValueError:
                raise _invalid(f"invalid string literal at position {i}") from None
            out.append(_Tok("str", raw, i, cast(str, parsed)))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()[]"':
                j += 1
            word = text[i:j]
            if _NUMBER.fullmatch(word):
                num: int | float = float(word) if re.search(r"[.eE]", word) else int(word)
                out.append(_Tok("num", word, i, num))
            else:
                out.append(_Tok("word", word, i))
            i = j
    return out


class _Parser:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.toks = tokens
        self.i = 0

    def peek(self) -> _Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise _invalid("unexpected end of filter")
        self.i += 1
        return tok

    def expect(self, kind: str) -> None:
        tok = self.next()
        if tok.kind != kind:
            raise _invalid(f"expected '{kind}' at position {tok.pos}, found '{tok.text}'")

    def is_word(self, word: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "word" and tok.text.lower() == word

    def parse_or(self, in_path: bool) -> Filter:
        left = self.parse_and(in_path)
        while self.is_word("or"):
            self.i += 1
            left = Or(left, self.parse_and(in_path))
        return left

    def parse_and(self, in_path: bool) -> Filter:
        left = self.parse_unary(in_path)
        while self.is_word("and"):
            self.i += 1
            left = And(left, self.parse_unary(in_path))
        return left

    def parse_unary(self, in_path: bool) -> Filter:
        tok = self.next()
        if tok.kind == "(":
            inner = self.parse_or(in_path)
            self.expect(")")
            return inner
        if tok.kind != "word":
            raise _invalid(f"unexpected '{tok.text}' at position {tok.pos}")
        if tok.text.lower() == "not":
            nxt = self.peek()
            if nxt is None or nxt.kind != "(":
                raise _invalid(f"'not' must be followed by '(' at position {tok.pos}")
            self.i += 1
            inner = self.parse_or(in_path)
            self.expect(")")
            return Not(inner)
        path = tok.text
        if not _PATH.fullmatch(path) or path.endswith(".") or path.endswith(":"):
            raise _invalid(f"invalid attribute path '{path}' at position {tok.pos}")
        nxt = self.peek()
        if nxt is not None and nxt.kind == "[":
            if in_path:
                raise _invalid(f"nested value paths are not allowed (position {nxt.pos})")
            self.i += 1
            inner = self.parse_or(True)
            self.expect("]")
            return self.after_value_path(path, inner)
        return self.comparison(path, tok)

    def after_value_path(self, path: str, inner: Filter) -> Filter:
        nxt = self.peek()
        if nxt is None or nxt.kind != "word" or not nxt.text.startswith("."):
            return ValuePath(path, inner)
        sub = nxt.text[1:]
        if not _ATTR.fullmatch(sub):
            raise _invalid(f"invalid sub-attribute '{nxt.text}' at position {nxt.pos}")
        self.i += 1
        following = self.peek()
        if (
            following is not None
            and following.kind == "word"
            and (following.text.lower() in OPERATORS)
        ):
            self.i += 1
            cmp = self.finish_comparison(sub, following)
        else:
            cmp = Compare(sub, "pr")
        return ValuePath(path, And(inner, cmp))

    def comparison(self, path: str, tok: _Tok) -> Filter:
        op_tok = self.peek()
        if op_tok is None:
            raise _invalid(f"missing operator after '{path}'")
        if op_tok.kind != "word":
            raise _invalid(f"expected an operator at position {op_tok.pos}, found '{op_tok.text}'")
        self.i += 1
        return self.finish_comparison(path, op_tok)

    def finish_comparison(self, path: str, op_tok: _Tok) -> Compare:
        op = op_tok.text.lower()
        if op not in OPERATORS:
            raise _invalid(f"unknown operator '{op_tok.text}' at position {op_tok.pos}")
        if op == "pr":
            return Compare(path, "pr")
        val = self.peek()
        if val is None:
            raise _invalid(f"missing value for operator '{op}'")
        self.i += 1
        value: Value
        if val.kind in ("str", "num"):
            value = val.value
        elif val.kind == "word" and val.text in ("true", "false", "null"):
            value = {"true": True, "false": False, "null": None}[val.text]
        else:
            raise _invalid(f"invalid value '{val.text}' at position {val.pos}")
        if op in ("co", "sw", "ew") and not isinstance(value, str):
            raise _invalid(f"operator '{op}' needs a string value")
        if op in ("gt", "ge", "lt", "le") and (value is None or isinstance(value, bool)):
            raise _invalid(f"operator '{op}' needs a string or number value")
        return Compare(path, op, value)


def parse(text: str) -> Filter:
    if not text.strip():
        raise _invalid("empty filter")
    parser = _Parser(_tokenize(text))
    flt = parser.parse_or(False)
    extra = parser.peek()
    if extra is not None:
        raise _invalid(f"unexpected '{extra.text}' at position {extra.pos}")
    return flt


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\5c")
        .replace("*", "\\2a")
        .replace("(", "\\28")
        .replace(")", "\\29")
        .replace("\x00", "\\00")
    )


def _literal(value: Value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return _escape(value)
    return str(value)


def _attr(path: str, prefix: str, resolve: Callable[[str], str | None]) -> str:
    full = f"{prefix}.{path.lower()}" if prefix else path.lower()
    attr = resolve(full)
    if attr is None:
        raise _invalid(f"attribute '{path}' cannot be used in a filter")
    return attr


def _compile(flt: Filter, resolve: Callable[[str], str | None], prefix: str) -> str:
    match flt:
        case And(left, right):
            return f"(&{_compile(left, resolve, prefix)}{_compile(right, resolve, prefix)})"
        case Or(left, right):
            return f"(|{_compile(left, resolve, prefix)}{_compile(right, resolve, prefix)})"
        case Not(inner):
            return f"(!{_compile(inner, resolve, prefix)})"
        case ValuePath(path, inner):
            return _compile(inner, resolve, f"{prefix}.{path.lower()}" if prefix else path.lower())
        case Compare(path, op, value):
            a = _attr(path, prefix, resolve)
            if op == "pr":
                return f"({a}=*)"
            if value is None:
                return f"(!({a}=*))" if op == "eq" else f"({a}=*)"
            v = _literal(value)
            return {
                "eq": f"({a}={v})",
                "ne": f"(!({a}={v}))",
                "co": f"({a}=*{v}*)",
                "sw": f"({a}={v}*)",
                "ew": f"({a}=*{v})",
                "gt": f"(&({a}>={v})(!({a}={v})))",
                "ge": f"({a}>={v})",
                "lt": f"(&({a}<={v})(!({a}={v})))",
                "le": f"({a}<={v})",
            }[op]


def to_ldap(flt: Filter, resolve: Callable[[str], str | None]) -> str:
    return _compile(flt, resolve, "")


def _collect(flt: Filter, resolve: Callable[[str], str | None], prefix: str, out: set[str]) -> None:
    match flt:
        case And(left, right) | Or(left, right):
            _collect(left, resolve, prefix, out)
            _collect(right, resolve, prefix, out)
        case Not(inner):
            _collect(inner, resolve, prefix, out)
        case ValuePath(path, inner):
            _collect(inner, resolve, f"{prefix}.{path.lower()}" if prefix else path.lower(), out)
        case Compare(path, _, _):
            out.add(_attr(path, prefix, resolve))


def attributes_of(flt: Filter, resolve: Callable[[str], str | None]) -> set[str]:
    out: set[str] = set()
    _collect(flt, resolve, "", out)
    return out


def _as_map(x: object) -> Mapping[str, Any] | None:
    return cast("Mapping[str, Any]", x) if isinstance(x, Mapping) else None


def _present(v: object) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def _lookup(node: Mapping[str, Any], name: str) -> tuple[bool, Any]:
    low = name.lower()
    for key, val in node.items():
        if key.lower() == low:
            return True, val
    return False, None


def _values(resource: Mapping[str, Any], path: str) -> list[Any]:
    urn, rest = split_path(path)
    base: Mapping[str, Any] = resource
    if urn is not None:
        found, ext = _lookup(resource, urn)
        ext_map = _as_map(ext) if found else None
        if ext_map is not None:
            base = ext_map
        elif ":core:" not in urn.lower():
            return []
        if not rest:
            return [ext_map] if ext_map is not None else []
    current: list[Any] = [base]
    for seg in rest.split("."):
        nxt: list[Any] = []
        for node in current:
            m = _as_map(node)
            if m is None:
                continue
            found, val = _lookup(m, seg)
            if not found:
                continue
            if isinstance(val, list):
                nxt.extend(cast("list[Any]", val))
            else:
                nxt.append(val)
        current = nxt
    return current


def _is_num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _equal(actual: object, expected: Value) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    if _is_num(actual) and _is_num(expected):
        return actual == expected
    return False


def _order(actual: object, expected: Value) -> int | None:
    a: object = actual
    e: object = expected
    if isinstance(a, str) and isinstance(e, str):
        a, e = a.casefold(), e.casefold()
    elif not (_is_num(a) and _is_num(e)):
        return None
    return (a > e) - (a < e)  # type: ignore[operator]


def _compare_one(op: str, actual: object, expected: Value) -> bool:
    if op == "eq":
        return _equal(actual, expected)
    if op in ("co", "sw", "ew"):
        if not (isinstance(actual, str) and isinstance(expected, str)):
            return False
        a, e = actual.casefold(), expected.casefold()
        return e in a if op == "co" else a.startswith(e) if op == "sw" else a.endswith(e)
    cmp = _order(actual, expected)
    if cmp is None:
        return False
    return {"gt": cmp > 0, "ge": cmp >= 0, "lt": cmp < 0, "le": cmp <= 0}[op]


def matches(flt: Filter, resource: Mapping[str, Any]) -> bool:
    match flt:
        case And(left, right):
            return matches(left, resource) and matches(right, resource)
        case Or(left, right):
            return matches(left, resource) or matches(right, resource)
        case Not(inner):
            return not matches(inner, resource)
        case ValuePath(path, inner):
            for element in _values(resource, path):
                m = _as_map(element)
                if m is not None and matches(inner, m):
                    return True
            return False
        case Compare(path, op, value):
            vals = _values(resource, path)
            if op == "pr":
                return any(_present(v) for v in vals)
            if op == "eq" and value is None:
                return not any(_present(v) for v in vals)
            if op == "ne":
                if value is None:
                    return any(_present(v) for v in vals)
                return not any(_compare_one("eq", v, value) for v in vals)
            return any(_compare_one(op, v, value) for v in vals)


__all__ = [
    "OPERATORS",
    "And",
    "Compare",
    "Filter",
    "Not",
    "Or",
    "Value",
    "ValuePath",
    "attributes_of",
    "matches",
    "parse",
    "split_path",
    "to_ldap",
]
