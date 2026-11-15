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

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from heracles.scim import filter as flt
from heracles.scim.errors import (
    INVALID_PATH,
    INVALID_SYNTAX,
    INVALID_VALUE,
    MUTABILITY,
    NO_TARGET,
    ScimError,
)
from heracles.scim.schemas import PATCH_OP

_OPS = ("add", "replace", "remove")
_ATTR = re.compile(r"[A-Za-z][A-Za-z0-9_$\-]*")


@dataclass(frozen=True, slots=True)
class PatchOp:
    op: str
    path: str | None
    value: Any = None


def parse_patch(body: Mapping[str, Any]) -> list[PatchOp]:
    schemas = body.get("schemas")
    if not isinstance(schemas, list) or PATCH_OP not in cast("list[Any]", schemas):
        raise ScimError(400, f"'schemas' must contain {PATCH_OP}", INVALID_SYNTAX)
    raw = body.get("Operations")
    if not isinstance(raw, list) or not raw:
        raise ScimError(400, "'Operations' must be a non-empty list", INVALID_SYNTAX)
    out: list[PatchOp] = []
    for i, item in enumerate(cast("list[Any]", raw)):
        if not isinstance(item, Mapping):
            raise ScimError(400, f"operation {i} must be an object", INVALID_SYNTAX)
        entry = cast("Mapping[str, Any]", item)
        op = entry.get("op")
        if not isinstance(op, str) or op.lower() not in _OPS:
            raise ScimError(
                400, f"operation {i}: 'op' must be add, replace or remove", INVALID_SYNTAX
            )
        op = op.lower()
        path = entry.get("path")
        if path is not None and (not isinstance(path, str) or not path.strip()):
            raise ScimError(
                400, f"operation {i}: 'path' must be a non-empty string", INVALID_SYNTAX
            )
        if op == "remove" and path is None:
            raise ScimError(400, f"operation {i}: 'remove' requires a 'path'", NO_TARGET)
        if op != "remove" and "value" not in entry:
            raise ScimError(400, f"operation {i}: '{op}' requires a 'value'", INVALID_SYNTAX)
        out.append(PatchOp(op, path, entry.get("value")))
    return out


@dataclass(frozen=True, slots=True)
class _Target:
    urn: str | None
    attr: str  # "" when the path is a bare schema URN
    sub: str | None
    filter: flt.Filter | None


def _bad_path(path: str, why: str) -> ScimError:
    return ScimError(400, f"invalid path '{path}': {why}", INVALID_PATH)


def _has_value_path(f: flt.Filter) -> bool:
    if isinstance(f, flt.ValuePath):
        return True
    if isinstance(f, (flt.And, flt.Or)):
        return _has_value_path(f.left) or _has_value_path(f.right)
    if isinstance(f, flt.Not):
        return _has_value_path(f.inner)
    return False


def _parse_target(path: str) -> _Target:
    br = path.find("[")
    head, tail = (path, "") if br < 0 else (path[:br], path[br:])
    urn, rest = flt.split_path(head)
    sub: str | None = None
    filt: flt.Filter | None = None
    if tail:
        # find the first unquoted closing bracket
        i, n, in_str = 1, len(tail), False
        while i < n:
            c = tail[i]
            if in_str:
                if c == "\\":
                    i += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "]":
                break
            i += 1
        else:
            raise _bad_path(path, "missing ']'")
        filt = flt.parse(tail[1:i])
        if _has_value_path(filt):
            raise ScimError(400, f"invalid path '{path}': nested value paths", INVALID_PATH)
        after = tail[i + 1 :]
        if after:
            if not after.startswith(".") or not _ATTR.fullmatch(after[1:]):
                raise _bad_path(path, "unexpected text after ']'")
            sub = after[1:]
        if not _ATTR.fullmatch(rest):
            raise _bad_path(path, "bad attribute name")
        return _Target(urn, rest, sub, filt)
    if rest == "" and urn is not None:
        return _Target(urn, "", None, None)
    parts = rest.split(".")
    if len(parts) > 2 or not all(_ATTR.fullmatch(p) for p in parts):
        raise _bad_path(path, "bad attribute name")
    return _Target(urn, parts[0], parts[1] if len(parts) == 2 else None, None)


def _find(d: Mapping[str, Any], name: str) -> str | None:
    low = name.lower()
    for k in d:
        if k.lower() == low:
            return k
    return None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        ma, mb = cast("Mapping[str, Any]", a), cast("Mapping[str, Any]", b)
        if "value" in ma and "value" in mb:
            return ma["value"] == mb["value"]
    return a == b


def _container(res: dict[str, Any], t: _Target, create: bool) -> dict[str, Any] | None:
    if t.urn is None or ":core:" in t.urn.lower():
        return res
    key = _find(res, t.urn)
    if key is None:
        if not create:
            return None
        res[t.urn] = {}
        key = t.urn
    ext = res[key]
    if not isinstance(ext, dict):
        raise ScimError(400, f"'{t.urn}' is not an object", INVALID_PATH)
    return cast("dict[str, Any]", ext)


def _elements(cont: dict[str, Any], key: str | None) -> list[Any]:
    if key is None:
        return []
    val = cont[key]
    return cast("list[Any]", val) if isinstance(val, list) else [val]


def _as_dict(x: Any, path: str) -> dict[str, Any]:
    if not isinstance(x, Mapping):
        raise ScimError(400, f"value for '{path}' must be an object", INVALID_VALUE)
    return dict(cast("Mapping[str, Any]", x))


def _check_readonly(path: str, t: _Target, readonly: Callable[[str], bool]) -> None:
    if not t.attr:
        return
    names = [t.attr.lower()]
    if t.sub:
        names.append(f"{t.attr}.{t.sub}".lower())
    for name in names:
        if readonly(name):
            raise ScimError(400, f"attribute '{path}' is read-only", MUTABILITY)


def _apply_one(
    res: dict[str, Any],
    op: str,
    path: str,
    value: Any,
    multi: Callable[[str], bool],
    readonly: Callable[[str], bool],
) -> None:
    t = _parse_target(path)
    _check_readonly(path, t, readonly)
    cont = _container(res, t, create=op != "remove")
    if cont is None:
        return
    if not t.attr:  # bare extension URN
        key = _find(res, cast(str, t.urn)) or cast(str, t.urn)
        if op == "remove":
            res.pop(key, None)
        elif op == "replace" or key not in res:
            res[key] = _as_dict(value, path)
        else:
            res[key].update(_as_dict(value, path))
        return
    key = _find(cont, t.attr)
    is_multi = multi(t.attr.lower())
    if t.filter is None and t.sub is None:
        _whole(cont, key, t.attr, op, value, is_multi)
    elif t.filter is None:
        _sub(cont, key, t, op, value, is_multi, path)
    else:
        _filtered(cont, key, t, op, value, path)
    if op == "remove" and t.urn is not None and ":core:" not in t.urn.lower() and not cont:
        res.pop(_find(res, t.urn) or t.urn, None)


def _whole(
    cont: dict[str, Any], key: str | None, attr: str, op: str, value: Any, is_multi: bool
) -> None:
    if op == "remove":
        if key is None:
            return
        if value is not None and is_multi:
            drop = cast("list[Any]", value) if isinstance(value, list) else [value]
            left = [e for e in _elements(cont, key) if not any(_same(e, d) for d in drop)]
            if left:
                cont[key] = left
            else:
                del cont[key]
        else:
            del cont[key]
        return
    k = key or attr
    if is_multi:
        vals = cast("list[Any]", value) if isinstance(value, list) else [value]
        if op == "replace":
            cont[k] = copy.deepcopy(vals)
            return
        cur = _elements(cont, key) if key is not None else []
        for v in vals:
            if not any(_same(e, v) for e in cur):
                cur.append(copy.deepcopy(v))
        cont[k] = cur
    elif op == "add" and isinstance(value, Mapping) and isinstance(cont.get(k), dict):
        cast("dict[str, Any]", cont[k]).update(_as_dict(value, attr))
    else:
        cont[k] = copy.deepcopy(cast("Any", value))


def _sub(
    cont: dict[str, Any],
    key: str | None,
    t: _Target,
    op: str,
    value: Any,
    is_multi: bool,
    path: str,
) -> None:
    sub = cast(str, t.sub)
    if is_multi:
        elems = cast(
            "list[dict[str, Any]]", [e for e in _elements(cont, key) if isinstance(e, dict)]
        )
        if not elems:
            if op == "remove":
                return
            raise ScimError(400, f"no value to modify at '{path}'", NO_TARGET)
        for e in elems:
            _set_sub(e, sub, op, value)
        return
    if key is None:
        if op == "remove":
            return
        cont[t.attr] = {}
        key = t.attr
    target = cont[key]
    if not isinstance(target, dict):
        raise _bad_path(path, f"'{t.attr}' has no sub-attributes")
    _set_sub(cast("dict[str, Any]", target), sub, op, value)
    if op == "remove" and not target:
        del cont[key]


def _set_sub(d: dict[str, Any], sub: str, op: str, value: Any) -> None:
    k = _find(d, sub)
    if op == "remove":
        if k is not None:
            del d[k]
    else:
        d[k or sub] = copy.deepcopy(value)


def _filtered(
    cont: dict[str, Any], key: str | None, t: _Target, op: str, value: Any, path: str
) -> None:
    assert t.filter is not None
    elems = _elements(cont, key)
    hits = [
        i
        for i, e in enumerate(elems)
        if isinstance(e, Mapping) and flt.matches(t.filter, cast("Mapping[str, Any]", e))
    ]
    if not hits:
        if op == "remove":
            return
        raise ScimError(400, f"no value matches the filter in '{path}'", NO_TARGET)
    k = cast(str, key)
    if t.sub is not None:
        for i in hits:
            _set_sub(cast("dict[str, Any]", elems[i]), t.sub, op, value)
    elif op == "remove":
        keep = [e for i, e in enumerate(elems) if i not in hits]
        if keep:
            cont[k] = keep
        else:
            del cont[k]
        return
    elif op == "replace":
        for i in hits:
            elems[i] = _as_dict(value, path)
    else:
        for i in hits:
            cast("dict[str, Any]", elems[i]).update(_as_dict(value, path))
    if k in cont:
        cont[k] = elems


def _apply_op(
    res: dict[str, Any],
    op: PatchOp,
    multi: Callable[[str], bool],
    readonly: Callable[[str], bool],
) -> None:
    if op.path is not None:
        _apply_one(res, op.op, op.path, op.value, multi, readonly)
        return
    raw: object = op.value
    if not isinstance(raw, Mapping):
        raise ScimError(400, f"'{op.op}' without a path needs an object value", INVALID_VALUE)
    items = cast("Mapping[str, Any]", raw)
    for k, v in items.items():
        if k.lower().startswith("urn:") and flt.split_path(k)[1] == "":
            if not isinstance(v, Mapping):
                raise ScimError(400, f"value of '{k}' must be an object", INVALID_VALUE)
            for sk, sv in cast("Mapping[str, Any]", v).items():
                _apply_one(res, op.op, f"{k}:{sk}", sv, multi, readonly)
        else:
            _apply_one(res, op.op, k, v, multi, readonly)


def apply_patch(
    resource: Mapping[str, Any],
    ops: list[PatchOp],
    *,
    multi_valued: Callable[[str], bool],
    readonly: Callable[[str], bool] = lambda _path: False,
) -> dict[str, Any]:
    res: dict[str, Any] = copy.deepcopy(dict(resource))
    for op in ops:
        _apply_op(res, op, multi_valued, readonly)
    return res


__all__ = ["PatchOp", "apply_patch", "parse_patch"]
