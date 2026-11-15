"""Helpers mapping SCIM resource shapes (pure: no directory access)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC
from typing import Any, cast

from heracles.core.generalized_time import parse_generalized_time
from heracles.scim.schemas import ENTERPRISE_USER_SCHEMA

#: Lower-cased prefix of the enterprise extension attributes in the settings map.
ENTERPRISE_PREFIX = ENTERPRISE_USER_SCHEMA.lower() + ":"

#: Canonical spelling of the attribute paths of the default mapping (lower-case -> canonical).
CANONICAL: dict[str, str] = {
    "username": "userName",
    "name.familyname": "name.familyName",
    "name.givenname": "name.givenName",
    "name.formatted": "name.formatted",
    "name.middlename": "name.middleName",
    "displayname": "displayName",
    "nickname": "nickName",
    "preferredlanguage": "preferredLanguage",
    "usertype": "userType",
    "title": "title",
    "locale": "locale",
    "profileurl": "profileUrl",
    "employeenumber": "employeeNumber",
    "costcenter": "costCenter",
}

#: Attributes whose value is a list of complex values (for the PATCH engine).
USER_MULTI = frozenset({"emails", "phonenumbers", "groups"})
GROUP_MULTI = frozenset({"members"})


def obj(value: object) -> dict[str, Any] | None:
    """``value`` as a JSON object, or ``None``."""
    if isinstance(value, Mapping):
        return {str(k): v for k, v in cast("Mapping[Any, Any]", value).items()}
    return None


def arr(value: object) -> list[Any] | None:
    """``value`` as a JSON array, or ``None``."""
    if isinstance(value, list):
        return list(cast("list[Any]", value))
    return None


def flatten(resource: Mapping[str, Any]) -> dict[str, Any]:
    """Lower-cased flat view of a resource: ``name.familyname``, URN-prefixed extension keys."""
    out: dict[str, Any] = {}
    for key, value in resource.items():
        low = key.lower()
        sub = obj(value)
        if low == ENTERPRISE_USER_SCHEMA.lower() and sub is not None:
            for name, item in sub.items():
                out[ENTERPRISE_PREFIX + name.lower()] = item
        elif sub is not None and low not in ("meta", "manager"):
            for name, item in sub.items():
                out[f"{low}.{name.lower()}"] = item
            out.setdefault(low, sub)
        else:
            out[low] = value
    return out


def place(resource: dict[str, Any], key: str, value: Any) -> None:
    """Store ``value`` at the lower-cased path ``key`` with its canonical spelling."""
    if key.startswith(ENTERPRISE_PREFIX):
        name = key[len(ENTERPRISE_PREFIX) :]
        ext = resource.setdefault(ENTERPRISE_USER_SCHEMA, {})
        ext[CANONICAL.get(name, name)] = value
        return
    canonical = CANONICAL.get(key, key)
    if "." in canonical:
        top, _, sub = canonical.partition(".")
        resource.setdefault(top, {})[sub] = value
    else:
        resource[canonical] = value


def canonical_path(key: str) -> str:
    """Display spelling of a lower-cased path (for error messages)."""
    if key.startswith(ENTERPRISE_PREFIX):
        name = key[len(ENTERPRISE_PREFIX) :]
        return CANONICAL.get(name, name)
    return CANONICAL.get(key, key)


def rfc3339(generalized: str | None) -> str | None:
    """LDAP generalized time -> ``YYYY-MM-DDTHH:MM:SSZ`` (``None`` when absent or invalid)."""
    if not generalized:
        return None
    try:
        moment = parse_generalized_time(generalized).astimezone(UTC)
    except ValueError:
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def version_of(resource: Mapping[str, Any]) -> str:
    """Weak ETag of a resource without ``meta`` (and without the derived ``groups``)."""
    body = {k: v for k, v in resource.items() if k not in ("meta", "groups")}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f'W/"{hashlib.sha256(raw.encode()).hexdigest()[:32]}"'


def primary(
    items: list[dict[str, Any]], preferred_type: str | None = None
) -> dict[str, Any] | None:
    """The primary item, else the first of ``preferred_type``, else the first."""
    for item in items:
        if item.get("primary") is True:
            return item
    if preferred_type is not None:
        for item in items:
            if str(item.get("type", "")).lower() == preferred_type:
                return item
    return items[0] if items else None
