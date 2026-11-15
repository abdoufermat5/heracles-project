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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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


def parse(text: str) -> Filter:
    raise NotImplementedError


def to_ldap(flt: Filter, resolve: Callable[[str], str | None]) -> str:
    raise NotImplementedError


def attributes_of(flt: Filter, resolve: Callable[[str], str | None]) -> set[str]:
    raise NotImplementedError


def matches(flt: Filter, resource: Mapping[str, Any]) -> bool:
    raise NotImplementedError


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
    "to_ldap",
]
