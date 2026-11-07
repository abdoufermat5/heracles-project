"""Parse and serialise role template values and assignment values."""

from __future__ import annotations

import base64
import binascii

import structlog

from heracles.acl.model import (
    ALL_USERS,
    AclAssignment,
    AclBlock,
    AclScope,
    Ignored,
    RoleTemplateValue,
)
from heracles.acl.rights import Rights, RightsParseError

log = structlog.get_logger(__name__)


def _b64d(text: str) -> str:
    """Strict base64 decode to UTF-8 text."""
    try:
        return base64.b64decode(text.encode("ascii"), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError(f"invalid base64 value {text!r}") from exc


def _b64e(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _ignored(raw: str, reason: str) -> Ignored:
    log.warning("acl_value_ignored", value=raw, reason=reason)
    return Ignored(raw, reason)


# ---------------------------------------------------------------- role templates


def _parse_block(text: str) -> AclBlock:
    head, *attr_parts = text.split("#")
    obj, _, rights_text = head.partition(";")
    obj = obj.strip()
    if not obj:
        raise ValueError("empty object key")
    attributes: list[tuple[str, Rights]] = []
    for part in attr_parts:
        name, _, attr_rights = part.partition(";")
        if not name:
            raise ValueError("empty attribute name")
        attributes.append((name, Rights.parse(attr_rights)))
    return AclBlock(obj, Rights.parse(rights_text), tuple(attributes))


def parse_role_value(value: str) -> RoleTemplateValue | Ignored:
    """Parse ``<index>:<object blocks>``; unusable values are returned as :class:`Ignored`."""
    index_text, sep, spec = value.partition(":")
    if not sep or not index_text.isascii() or not index_text.isdigit():
        return _ignored(value, "invalid role value index")
    blocks: list[AclBlock] = []
    try:
        if spec:
            blocks = [_parse_block(part) for part in spec.split(",")]
    except (ValueError, RightsParseError) as exc:
        return _ignored(value, f"invalid role value: {exc}")
    return RoleTemplateValue(int(index_text), tuple(blocks))


def serialise_role_value(value: RoleTemplateValue) -> str:
    """Inverse of :func:`parse_role_value`."""
    blocks: list[str] = []
    for block in value.blocks:
        text = f"{block.object};{block.rights}"
        for name, rights in block.attributes:
            text += f"#{name};{rights}"
        blocks.append(text)
    return f"{value.index}:{','.join(blocks)}"


# ------------------------------------------------------------------ assignments


def parse_assignment(value: str) -> AclAssignment | Ignored:
    """Parse an assignment value.

    ``<index>:<scope>:<roleDn b64>:<members>[:<userfilter b64>[:<targetfilter b64>]]``.
    Unknown scopes (including the retired ``one`` / ``psub``) and malformed values
    are reported as :class:`Ignored` and logged as warnings.
    """
    parts = value.split(":")
    if not 4 <= len(parts) <= 6:
        return _ignored(value, "wrong number of fields")
    index_text, scope_text, role_b64, members_b64, *filters = parts
    if not index_text.isascii() or not index_text.isdigit():
        return _ignored(value, "invalid index")
    try:
        scope = AclScope(scope_text)
    except ValueError:
        return _ignored(value, f"unsupported scope {scope_text!r}")
    try:
        role_dn = _b64d(role_b64)
        members = tuple(_b64d(m) for m in members_b64.split(",") if m)
        decoded = [_b64d(f) for f in filters]
    except ValueError as exc:
        return _ignored(value, str(exc))
    if not role_dn:
        return _ignored(value, "empty role DN")
    user_filter = decoded[0] if decoded and decoded[0] else None
    target_filter = decoded[1] if len(decoded) > 1 and decoded[1] else None
    return AclAssignment(
        index=int(index_text),
        scope=scope,
        role_dn=role_dn,
        members=members,
        user_filter=user_filter,
        target_filter=target_filter,
    )


def serialise_assignment(assignment: AclAssignment) -> str:
    """Inverse of :func:`parse_assignment`."""
    members = ",".join(_b64e(m) for m in assignment.members)
    text = f"{assignment.index}:{assignment.scope.value}:{_b64e(assignment.role_dn)}:{members}"
    if assignment.user_filter is not None or assignment.target_filter is not None:
        text += ":" + (_b64e(assignment.user_filter) if assignment.user_filter else "")
    if assignment.target_filter is not None:
        text += ":" + _b64e(assignment.target_filter)
    return text


def everyone_member() -> str:
    """The member literal for all users, as stored (base64 of ``*``)."""
    return _b64e(ALL_USERS)
