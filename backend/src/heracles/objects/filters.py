"""LDAP search filter helpers (RFC 4515 escaping)."""

from __future__ import annotations

from collections.abc import Sequence

_ESCAPES = {"\\": r"\5c", "*": r"\2a", "(": r"\28", ")": r"\29", "\x00": r"\00"}


def escape_filter_value(value: str) -> str:
    """Escape ``value`` for use as an assertion value in a filter."""
    return "".join(_ESCAPES.get(ch, ch) for ch in value)


def equals(attr: str, value: str) -> str:
    """``(attr=value)`` with the value escaped."""
    return f"({attr}={escape_filter_value(value)})"


def and_(*parts: str) -> str:
    """Conjunction of filters (a single part is returned as is)."""
    items = [p for p in parts if p]
    return items[0] if len(items) == 1 else "(&" + "".join(items) + ")"


def or_(parts: Sequence[str]) -> str:
    """Disjunction of filters (a single part is returned as is)."""
    return parts[0] if len(parts) == 1 else "(|" + "".join(parts) + ")"


def text_query(attrs: Sequence[str], query: str) -> str:
    """Match every whitespace separated word of ``query`` in any of ``attrs`` (substring)."""
    words = query.split()
    if not words or not attrs:
        return ""
    clauses = [or_([f"({a}=*{escape_filter_value(w)}*)" for a in attrs]) for w in words]
    return and_(*clauses)
