"""SCIM PATCH (RFC 7644 section 3.5.2) applied to a resource dict.

Owner: stream A. Contract:

* :func:`parse_patch` validates a request body (``schemas`` holds ``PATCH_OP``,
  ``Operations`` a non-empty list; ``op`` case-insensitive ``add``/``replace``/``remove``;
  ``path`` optional except for ``remove``) and returns :class:`PatchOp` items, ``op``
  lower-cased. Errors: ``ScimError(400, ..., INVALID_SYNTAX)`` (or ``NO_TARGET`` for a
  ``remove`` without path).
* :func:`apply_patch` returns a new resource (the input is not mutated). Paths: ``attr``,
  ``attr.sub``, ``attr[filter]``, ``attr[filter].sub``, each optionally prefixed by a schema
  URN and ``:`` (``urn:...:enterprise:2.0:User:employeeNumber``, which addresses the
  extension object of that URN in the resource). Attribute names match case-insensitively;
  the stored key keeps the resource's existing spelling, else the one in the path.
  Semantics of RFC 7644 3.5.2.1-3: ``add`` to a multi-valued attribute appends (no
  duplicates), to a single-valued one replaces, without path merges the value object;
  ``replace`` replaces (a value-path ``replace`` replaces the matching values or their
  sub-attribute; no match -> ``NO_TARGET``); ``remove`` removes the attribute or the
  matching values. Which attributes are multi-valued comes from ``multi_valued(path)``
  (lower-cased path, URN prefix stripped). Bad paths -> ``INVALID_PATH``; filter errors ->
  ``INVALID_FILTER``. ``readonly(path)`` attributes (``id``, ``meta``...) -> 400
  ``MUTABILITY``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PatchOp:
    op: str
    path: str | None
    value: Any = None


def parse_patch(body: Mapping[str, Any]) -> list[PatchOp]:
    raise NotImplementedError


def apply_patch(
    resource: Mapping[str, Any],
    ops: list[PatchOp],
    *,
    multi_valued: Callable[[str], bool],
    readonly: Callable[[str], bool] = lambda _path: False,
) -> dict[str, Any]:
    raise NotImplementedError


__all__ = ["PatchOp", "apply_patch", "parse_patch"]
