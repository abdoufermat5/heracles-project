"""``attributes`` / ``excludedAttributes`` (RFC 7644 section 3.4.2.5).

Owner: stream A. Contract: :func:`project` returns a new resource keeping only the listed
attributes (``attributes``) or dropping them (``excludedAttributes``); both are lists of
paths (``userName``, ``name.givenName``, ``emails``, ``urn:...:User:employeeNumber``),
matched case-insensitively. ``always`` attributes are kept whatever is asked (``id``,
``schemas``, and ``meta`` is kept unless excluded explicitly... see RFC 7643 "returned").
Giving both lists is the caller's 400; this function receives at most one non-empty list.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, cast

from heracles.scim.filter import split_path

ALWAYS = ("id", "schemas")

type _Path = tuple[str, ...]


def _paths(items: Sequence[str]) -> list[_Path]:
    out: list[_Path] = []
    for item in items:
        urn, rest = split_path(item.strip())
        segs = tuple(s.lower() for s in rest.split(".") if s)
        if urn is not None and ":core:" not in urn.lower():
            segs = (urn.lower(), *segs)
        elif urn is not None and not segs:
            continue
        if segs:
            out.append(segs)
    return out


def _children(paths: list[_Path], key: str) -> list[_Path]:
    return [p for p in paths if p[0] == key]


def _walk(value: Any, paths: list[_Path], keep: bool) -> tuple[bool, Any]:
    """Return ``(kept, value)`` for a nested value; ``paths`` are relative to it."""
    if isinstance(value, list):
        items: list[Any] = []
        for el in cast("list[Any]", value):
            ok, out = _walk(el, paths, keep)
            if ok:
                items.append(out)
        return (bool(items) or not keep, items)
    if isinstance(value, Mapping):
        out_map = _filter_map(cast("Mapping[str, Any]", value), paths, keep, ())
        return (bool(out_map) or not keep, out_map)
    return (not keep, value)


def _filter_map(
    node: Mapping[str, Any], paths: list[_Path], keep: bool, always: Sequence[str]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pinned = {a.lower() for a in always}
    for key, val in node.items():
        low = key.lower()
        if low in pinned:
            out[key] = copy.deepcopy(val)
            continue
        hits = _children(paths, low)
        if any(len(p) == 1 for p in hits):
            if keep:
                out[key] = copy.deepcopy(val)
            continue
        if not hits:
            if not keep:
                out[key] = copy.deepcopy(val)
            continue
        ok, sub = _walk(val, [p[1:] for p in hits], keep)
        if ok:
            out[key] = sub
    return out


def project(
    resource: Mapping[str, Any],
    attributes: Sequence[str] = (),
    excluded: Sequence[str] = (),
    always: Sequence[str] = ALWAYS,
) -> dict[str, Any]:
    inc, exc = _paths(attributes), _paths(excluded)
    if inc:
        return _filter_map(resource, inc, True, always)
    if exc:
        return _filter_map(resource, exc, False, always)
    return copy.deepcopy(dict(resource))


__all__ = ["ALWAYS", "project"]
