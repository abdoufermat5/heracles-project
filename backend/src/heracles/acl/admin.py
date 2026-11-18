"""Management of ACL roles and ACL assignments (the data the engine evaluates).

Role templates and assignment values round-trip byte for byte: a value that is
sent back unchanged keeps its original text, and values this module cannot parse
are carried through untouched (they can only be removed explicitly).
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from heracles.acl._names import (
    ATTR_ACL_ENTRY,
    ATTR_ACL_TEMPLATE,
    OC_ACL,
    OC_ACL_ROLE,
)
from heracles.acl.evaluator import AclEvaluator
from heracles.acl.model import (
    ALL_USERS,
    AclAssignment,
    AclBlock,
    AclScope,
    Ignored,
    RoleTemplateValue,
)
from heracles.acl.parser import (
    parse_assignment,
    parse_role_value,
    serialise_assignment,
    serialise_role_value,
)
from heracles.acl.resolver import AclResolver, AssignmentEntry
from heracles.acl.rights import NO_RIGHTS, Rights, RightsParseError
from heracles.core.containers import ensure_container
from heracles.core.formats import check as check_format
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.schema import names as schema

DEFAULT_ROLE_RDN = schema.RDN.ACL_ROLES
_FORBIDDEN_IN_NAMES = set(",#;:\n")
#: Longest role name and description (the directory allows more; screens stay readable).
ROLE_NAME_MAX = 64
ROLE_DESCRIPTION_MAX = 512
#: Characters a role name never contains: the template separators and the RDN specials.
_FORBIDDEN_IN_ROLE_NAMES = frozenset(',#;:+="<>\\')


class AclAdminError(ValueError):
    """Invalid role or assignment data; ``fields`` maps a path to a message."""

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = dict(fields)


class RoleInUseError(AclAdminError):
    """The role is still referenced by assignments."""


class UnheldRightsError(AclAdminError):
    """The change would grant rights the caller may not grant (``missing`` lists them)."""

    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__({"templates": "You cannot grant rights you do not hold."})
        self.missing = list(missing)


# ------------------------------------------------------------------ role values


def template_to_json(raw: str) -> dict[str, Any]:
    """JSON form of one role template value (unusable values keep ``raw`` only)."""
    parsed = parse_role_value(raw)
    if isinstance(parsed, Ignored):
        return {"raw": raw, "ignored": True, "reason": parsed.reason, "index": 0, "blocks": []}
    return {
        "raw": raw,
        "ignored": False,
        "index": parsed.index,
        "blocks": [
            {
                "object": b.object,
                "rights": str(b.rights),
                "attributes": [{"name": n, "rights": str(r)} for n, r in b.attributes],
            }
            for b in parsed.blocks
        ],
    }


def _check_name(label: str, name: str, path: str) -> None:
    if not name or any(ch in _FORBIDDEN_IN_NAMES for ch in name):
        raise AclAdminError({path: f"Invalid {label}."})


def check_role_name(name: str) -> str | None:
    """Why ``name`` cannot name a role, else ``None`` (the browser mirrors this rule)."""
    if not name:
        return "A name is required."
    if len(name) > ROLE_NAME_MAX:
        return f"Use at most {ROLE_NAME_MAX} characters."
    if any(ch in _FORBIDDEN_IN_ROLE_NAMES or ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return 'Do not use the characters , # ; : + = " < > \\ or control characters.'
    return None


def _check_description(text: str) -> None:
    if len(text) > ROLE_DESCRIPTION_MAX:
        raise AclAdminError({"description": f"Use at most {ROLE_DESCRIPTION_MAX} characters."})


def _rights(text: str, path: str) -> Rights:
    try:
        return Rights.parse(text)
    except RightsParseError as exc:
        raise AclAdminError({path: str(exc)}) from None


def template_from_json(item: Mapping[str, Any], path: str = "templates") -> str:
    """Serialise one template; unchanged values keep their stored spelling."""
    raw = item.get("raw")
    blocks_json = item.get("blocks")
    if bool(item.get("ignored")) and isinstance(raw, str):
        return raw
    if not isinstance(blocks_json, list):
        raise AclAdminError({path: "Expected a list of blocks."})
    blocks: list[AclBlock] = []
    for i, block_any in enumerate(cast("list[object]", blocks_json)):
        bpath = f"{path}.blocks.{i}"
        if not isinstance(block_any, dict):
            raise AclAdminError({bpath: "Expected an object."})
        block = cast("dict[str, Any]", block_any)
        obj = str(block.get("object", "")).strip()
        _check_name("object key", obj, f"{bpath}.object")
        attrs: list[tuple[str, Rights]] = []
        for j, attr_any in enumerate(cast("list[object]", block.get("attributes") or [])):
            apath = f"{bpath}.attributes.{j}"
            if not isinstance(attr_any, dict):
                raise AclAdminError({apath: "Expected an object."})
            attr = cast("dict[str, Any]", attr_any)
            name = str(attr.get("name", "")).strip()
            _check_name("attribute name", name, f"{apath}.name")
            problem = check_format("attribute", name)
            if problem is not None:
                raise AclAdminError({f"{apath}.name": problem})
            attrs.append((name, _rights(str(attr.get("rights", "")), f"{apath}.rights")))
        blocks.append(
            AclBlock(obj, _rights(str(block.get("rights", "")), f"{bpath}.rights"), tuple(attrs))
        )
    index_value = item.get("index", 0)
    index = index_value if isinstance(index_value, int) and index_value >= 0 else 0
    value = RoleTemplateValue(index, tuple(blocks))
    text = serialise_role_value(value)
    if isinstance(raw, str):
        original = parse_role_value(raw)
        if isinstance(original, RoleTemplateValue) and serialise_role_value(original) == text:
            return raw  # same structure: keep the stored spelling
    return text


# ------------------------------------------------------------------------ roles


@dataclass(frozen=True, slots=True)
class RoleInfo:
    dn: str
    cn: str
    description: str
    templates: tuple[str, ...]
    extra_classes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "dn": self.dn,
            "cn": self.cn,
            "description": self.description,
            "templates": [template_to_json(t) for t in self.templates],
        }


def _role_of(entry: Entry) -> RoleInfo:
    return RoleInfo(
        entry.dn,
        entry.text("cn") or "",
        entry.text("description") or "",
        tuple(entry.texts(ATTR_ACL_TEMPLATE)),
    )


def list_roles(directory: DirectoryClient, base: str | None = None) -> list[RoleInfo]:
    """Every ACL role below ``base`` (default: the directory base), sorted by name."""
    try:
        found = directory.search(base or directory.base_dn, f"(objectClass={OC_ACL_ROLE})")
        roles = [_role_of(e) for e in found]
    except NoSuchObjectError:
        return []
    return sorted(roles, key=lambda r: (r.cn.lower(), r.dn))


def get_role(directory: DirectoryClient, dn: str) -> RoleInfo | None:
    entry = directory.get(dn)
    if entry is None or not entry.has_object_class(OC_ACL_ROLE):
        return None
    return _role_of(entry)


def role_container(directory: DirectoryClient, department: str | None, rdn: str | None) -> str:
    return dnlib.join(rdn or DEFAULT_ROLE_RDN, department or directory.base_dn)


def _templates_from(items: Sequence[Mapping[str, Any]]) -> list[str]:
    if not items:
        raise AclAdminError({"templates": "A role needs at least one template."})
    return [template_from_json(item, f"templates.{i}") for i, item in enumerate(items)]


def create_role(
    directory: DirectoryClient,
    *,
    container: str,
    cn: str,
    description: str,
    templates: Sequence[Mapping[str, Any]],
    delegable: Delegable | None = None,
) -> str:
    """Create a role; with ``delegable``, refuse templates the caller may not grant.

    A new role is normally assigned nowhere, but an assignment left behind by a
    directory edit could already name its DN.
    """
    problem = check_role_name(cn.strip())
    if problem is not None:
        raise AclAdminError({"cn": problem})
    _check_description(description)
    values = _templates_from(templates)
    ensure_container(directory, container)
    dn = f"cn={dnlib.escape_rdn_value(cn.strip())},{container}"
    if delegable is not None:
        missing = unheld_template_grants(directory, dn, [], values, delegable=delegable)
        if missing:
            raise UnheldRightsError(missing)
    attrs: dict[str, list[bytes]] = {
        "objectClass": [OC_ACL_ROLE.encode()],
        "cn": [cn.strip().encode()],
        ATTR_ACL_TEMPLATE: [v.encode() for v in values],
    }
    if description.strip():
        attrs["description"] = [description.strip().encode()]
    try:
        directory.add(dn, attrs)
    except AlreadyExistsError:
        raise AclAdminError({"cn": "A role with this name already exists."}) from None
    return dn


def update_role(
    directory: DirectoryClient,
    dn: str,
    *,
    description: str | None,
    templates: Sequence[Mapping[str, Any]] | None,
    delegable: Delegable | None = None,
) -> RoleInfo:
    """Update a role; with ``delegable``, refuse template rights the caller may not grant."""
    current = get_role(directory, dn)
    if current is None:
        raise NoSuchObjectError(dn)
    mods: list[Modification] = []
    if description is not None:
        _check_description(description)
    if templates is not None:
        values = _templates_from(templates)
        if values != list(current.templates):
            if delegable is not None:
                missing = unheld_template_grants(
                    directory, dn, current.templates, values, delegable=delegable
                )
                if missing:
                    raise UnheldRightsError(missing)
            mods.append(Modification("replace", ATTR_ACL_TEMPLATE, [v.encode() for v in values]))
    if description is not None and description.strip() != current.description:
        if description.strip():
            mods.append(Modification("replace", "description", [description.strip().encode()]))
        elif current.description:
            mods.append(Modification("delete", "description"))
    if mods:
        directory.modify(dn, mods)
    updated = get_role(directory, dn)
    assert updated is not None
    return updated


def assignments_using_role(directory: DirectoryClient, role_dn: str) -> list[tuple[str, int]]:
    """``(entry dn, index)`` of every assignment referencing ``role_dn``."""
    target = dnlib.normalize(role_dn)
    out: list[tuple[str, int]] = []
    for entry in _assignment_entries(directory):
        for value in entry.values:
            parsed = parse_assignment(value)
            if isinstance(parsed, AclAssignment) and dnlib.normalize(parsed.role_dn) == target:
                out.append((entry.dn, parsed.index))
    return out


def role_use_counts(directory: DirectoryClient) -> dict[str, int]:
    """Number of assignments referencing each role (normalised role DN), in one search."""
    counts: dict[str, int] = {}
    for entry in _assignment_entries(directory):
        for value in entry.values:
            parsed = parse_assignment(value)
            if isinstance(parsed, AclAssignment):
                key = dnlib.normalize(parsed.role_dn)
                counts[key] = counts.get(key, 0) + 1
    return counts


def delete_role(directory: DirectoryClient, dn: str, *, force: bool = False) -> None:
    if get_role(directory, dn) is None:
        raise NoSuchObjectError(dn)
    users = assignments_using_role(directory, dn)
    if users and not force:
        raise RoleInUseError(
            {"dn": f"The role is used by {len(users)} assignment(s); remove them first."}
        )
    directory.delete(dn)


# ------------------------------------------------------------------ assignments


def _assignment_entries(directory: DirectoryClient) -> list[AssignmentEntry]:
    try:
        found = directory.search(
            directory.base_dn, f"(objectClass={OC_ACL})", Scope.SUBTREE, [ATTR_ACL_ENTRY]
        )
        return [AssignmentEntry(e.dn, e.texts(ATTR_ACL_ENTRY)) for e in found]
    except NoSuchObjectError:
        return []


def _member_kind(directory: DirectoryClient, member: str) -> str:
    if member == ALL_USERS:
        return "everyone"
    entry = directory.get(member, ["objectClass", "cn", "uid"])
    if entry is None:
        return "missing"
    if entry.has_object_class(schema.STD_OC.INET_ORG_PERSON):
        return "user"
    if entry.has_object_class(schema.STD_OC.ORGANIZATIONAL_ROLE):
        return "role"
    return "group"


def assignment_to_json(directory: DirectoryClient, raw: str) -> dict[str, Any]:
    parsed = parse_assignment(raw)
    if isinstance(parsed, Ignored):
        return {"raw": raw, "ignored": True, "reason": parsed.reason, "index": 0}
    role = directory.get(parsed.role_dn, ["cn"])
    return {
        "raw": raw,
        "ignored": False,
        "index": parsed.index,
        "scope": parsed.scope.value,
        "role": parsed.role_dn,
        "role_name": (role.text("cn") if role is not None else None) or None,
        "role_missing": role is None,
        "members": [{"dn": m, "kind": _member_kind(directory, m)} for m in parsed.members],
        "user_filter": parsed.user_filter,
        "target_filter": parsed.target_filter,
    }


def list_assignments(directory: DirectoryClient, dn: str) -> list[dict[str, Any]]:
    entry = directory.get(dn, [ATTR_ACL_ENTRY, "objectClass"])
    if entry is None:
        raise NoSuchObjectError(dn)
    items = [assignment_to_json(directory, v) for v in entry.texts(ATTR_ACL_ENTRY)]
    return sorted(items, key=lambda i: (i["index"], i["raw"]))


def all_assignments(directory: DirectoryClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in _assignment_entries(directory):
        out.append(
            {
                "dn": entry.dn,
                "assignments": [assignment_to_json(directory, v) for v in entry.values],
            }
        )
    return sorted(out, key=lambda e: (dnlib.depth(e["dn"]), e["dn"].lower()))


def assignment_from_json(item: Mapping[str, Any], path: str) -> str:
    raw = item.get("raw")
    if bool(item.get("ignored")) and isinstance(raw, str):
        return raw
    scope_text = str(item.get("scope", ""))
    try:
        scope = AclScope(scope_text)
    except ValueError:
        raise AclAdminError({f"{path}.scope": "Unknown scope."}) from None
    role = str(item.get("role", "")).strip()
    if not role:
        raise AclAdminError({f"{path}.role": "A role is required."})
    problem = check_format("dn", role)
    if problem is not None:
        raise AclAdminError({f"{path}.role": problem})
    members_raw = item.get("members")
    members: list[str] = []
    if not isinstance(members_raw, list):
        raise AclAdminError({f"{path}.members": "Expected a list."})
    for m in members_raw:  # pyright: ignore[reportUnknownVariableType]
        text = m.get("dn") if isinstance(m, dict) else m  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(text, str) or not text.strip():
            raise AclAdminError({f"{path}.members": "Invalid member."})
        text = text.strip()
        problem = None if text == ALL_USERS else check_format("dn", text)
        if problem is not None:
            raise AclAdminError({f"{path}.members": f"{text}: {problem}"})
        members.append(text)
    if not members:
        raise AclAdminError({f"{path}.members": "At least one member is required."})
    user_filter = str(item.get("user_filter") or "").strip() or None
    target_filter = str(item.get("target_filter") or "").strip() or None
    for key, text in (("user_filter", user_filter), ("target_filter", target_filter)):
        if text is None:
            continue
        problem = check_format("ldap_filter", text)
        if problem is not None:
            raise AclAdminError({f"{path}.{key}": problem})
    index_value = item.get("index", 0)
    index = index_value if isinstance(index_value, int) and index_value >= 0 else 0
    value = AclAssignment(index, scope, role, tuple(members), user_filter, target_filter)
    text = serialise_assignment(value)
    if isinstance(raw, str):
        original = parse_assignment(raw)
        if isinstance(original, AclAssignment) and serialise_assignment(original) == text:
            return raw
    return text


def _check_references(directory: DirectoryClient, value: str, path: str) -> None:
    """The role and the members of a new or changed assignment must exist."""
    parsed = parse_assignment(value)
    if not isinstance(parsed, AclAssignment):
        return
    if get_role(directory, parsed.role_dn) is None:
        raise AclAdminError({f"{path}.role": "This role does not exist."})
    for member in parsed.members:
        if member != ALL_USERS and directory.get(member, ["objectClass"]) is None:
            raise AclAdminError({f"{path}.members": f"{member}: this entry does not exist."})


def check_department(
    directory: DirectoryClient, dn: str, path: str = "base", *, exists: bool = True
) -> None:
    """``dn`` must be a well-formed DN; with ``exists``, of an entry below the directory base."""
    problem = check_format("dn", dn)
    if problem is not None:
        raise AclAdminError({path: problem})
    if not exists:
        return
    if not dnlib.is_descendant(dn, directory.base_dn) or directory.get(dn, ["objectClass"]) is None:
        raise AclAdminError({path: "This department does not exist."})


def set_assignments(
    directory: DirectoryClient, dn: str, items: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Replace the assignments of ``dn`` (the list order defines nothing, ``index`` does)."""
    entry = directory.get(dn, ["objectClass", ATTR_ACL_ENTRY])
    if entry is None:
        raise NoSuchObjectError(dn)
    values = [assignment_from_json(item, f"assignments.{i}") for i, item in enumerate(items)]
    stored = set(entry.texts(ATTR_ACL_ENTRY))
    for i, value in enumerate(values):
        if value not in stored:  # references kept as they were may be stale; new ones may not
            _check_references(directory, value, f"assignments.{i}")
    mods: list[Modification] = []
    if values:
        if not entry.has_object_class(OC_ACL):
            mods.append(Modification("add", "objectClass", [OC_ACL.encode()]))
        if sorted(values) != sorted(entry.texts(ATTR_ACL_ENTRY)):
            mods.append(Modification("replace", ATTR_ACL_ENTRY, [v.encode() for v in values]))
    elif entry.has_object_class(OC_ACL):
        mods.append(Modification("delete", ATTR_ACL_ENTRY))
        mods.append(Modification("delete", "objectClass", [OC_ACL.encode()]))
    if mods:
        directory.modify(dn, mods)
    return list_assignments(directory, dn)


def reorder(items: Sequence[Mapping[str, Any]], order: Sequence[int]) -> list[dict[str, Any]]:
    """Renumber ``items`` following ``order`` (positions into ``items``), indices 0..n-1."""
    out: list[dict[str, Any]] = []
    for new_index, position in enumerate(order):
        item = dict(items[position])
        item["index"] = new_index
        out.append(item)
    return out


# ------------------------------------------------------------------ rights check


@dataclass(slots=True)
class RightsReport:
    dn: str
    object_key: str
    rights: str
    attributes: dict[str, str] = field(default_factory=lambda: {})
    warnings: list[str] = field(default_factory=lambda: [])
    rules: list[dict[str, Any]] = field(default_factory=lambda: [])

    def to_json(self) -> dict[str, Any]:
        return {
            "dn": self.dn,
            "object": self.object_key,
            "rights": self.rights,
            "attributes": self.attributes,
            "warnings": self.warnings,
            "rules": self.rules,
        }


def _rights_text(rights: Rights) -> str:
    return rights.canonical().replace("s", "")


def check_rights(
    directory: DirectoryClient,
    *,
    user_dn: str,
    target_dn: str,
    object_key: str,
    attributes: Iterable[str] = (),
    category_tabs: Mapping[str, Sequence[str]] | None = None,
    target_limit: int = 100,
) -> RightsReport:
    """Effective rights of ``user_dn`` on ``object_key`` of ``target_dn``."""
    from heracles.acl.directory import LdapAclDirectory

    problems: dict[str, str] = {}
    for key, value in (("user", user_dn), ("dn", target_dn)):
        problem = "A value is required." if not value.strip() else check_format("dn", value)
        if problem is not None:
            problems[key] = problem
    if not object_key.strip():
        problems["object"] = "An object type is required."
    for name in attributes:
        problem = check_format("attribute", name)
        if problem is not None:
            problems["attributes"] = f"{name}: {problem}"
    if problems:
        raise AclAdminError(problems)
    entry = directory.get(user_dn)
    if entry is None:
        raise NoSuchObjectError(user_dn)
    attrs = {k: [v.decode("utf-8", "replace") for v in vals] for k, vals in entry.attrs.items()}
    resolved = AclResolver(LdapAclDirectory(directory), target_limit=target_limit).resolve(
        user_dn, uid=entry.text("uid"), user_attrs=attrs
    )
    evaluator = AclEvaluator(resolved, category_tabs=category_tabs)
    report = RightsReport(
        target_dn,
        object_key,
        _rights_text(evaluator.permissions(target_dn, object_key)),
        {a: _rights_text(evaluator.permissions(target_dn, object_key, a)) for a in attributes},
        [w.message for w in resolved.warnings],
    )
    nearest = resolved.nearest_view(target_dn)
    if nearest is not None:
        _, view = nearest
        report.rules = [
            {
                "origin": rule.origin,
                "scope": rule.scope.value,
                "blocks": sorted(rule.blocks),
                # blocks that only apply to the user's own entry (`s`): they never grant
                # anything on another entry such as a department
                "self_only": sorted(key for key, block in rule.blocks.items() if block.is_self),
            }
            for rule in view
        ]
    return report


def grants_everything(templates: Iterable[str]) -> bool:
    """True when one template value grants full rights on ``all`` (a super-administrator role)."""
    for raw in templates:
        parsed = parse_role_value(raw)
        if isinstance(parsed, Ignored):
            continue
        block = parsed.block_map().get("all")
        if block is not None and block.rights.is_full and not block.rights.self_only:
            return True
    return False


def _merged_blocks(templates: Iterable[str]) -> dict[str, AclBlock]:
    """Rights blocks of template values by object key (unusable values are skipped)."""
    merged: dict[str, AclBlock] = {}
    for raw in templates:
        parsed = parse_role_value(raw)
        if isinstance(parsed, Ignored):
            continue
        for key, block in parsed.block_map().items():
            previous = merged.get(key)
            merged[key] = block if previous is None else previous.merge(block)
    return merged


def role_blocks(directory: DirectoryClient, role_dn: str) -> list[AclBlock]:
    """Merged rights blocks of a role (empty when it is missing or has no usable value)."""
    entry = directory.get(role_dn, [ATTR_ACL_TEMPLATE])
    if entry is None:
        return []
    return list(_merged_blocks(entry.texts(ATTR_ACL_TEMPLATE)).values())


class Delegable(Protocol):
    """Rights the caller may grant to others (:meth:`AclEvaluator.delegable`)."""

    def __call__(
        self, dn: str, obj: str, attribute: str = "", /, *, below: bool = False
    ) -> Rights: ...


def _granted(block: AclBlock) -> list[tuple[str, Rights]]:
    """What a block grants: ``("", object rights)`` then ``(attribute, rights)``.

    The ``s`` flag is not a right: a self-only block still grants on the assignee's own
    entry, so its rights are required like any other.
    """
    out: list[tuple[str, Rights]] = [("", block.rights.union(block.self_rights).without_self())]
    by_name: dict[str, Rights] = {}
    for name, rights in block.attributes:
        key = name.lower()
        by_name[key] = by_name.get(key, NO_RIGHTS).union(rights.without_self())
    out.extend(by_name.items())
    return [(attr, rights) for attr, rights in out if not rights.is_empty]


def _unheld(
    blocks: Iterable[AclBlock],
    *,
    at: str,
    subtree: bool,
    delegable: Delegable,
    already: Mapping[str, AclBlock] | None = None,
) -> list[str]:
    """``<object key>[#attribute]:<rights>`` granted by ``blocks`` that the caller cannot grant.

    Object-level and per-attribute rights are checked separately: holding one attribute
    never covers the whole object. A subtree grant must be held at ``at`` and on every
    entry below it. Rights ``already`` granted (the role's previous templates) are skipped.
    """
    missing: list[str] = []
    for block in blocks:
        prior = already.get(block.object) if already else None
        previous = dict(_granted(prior)) if prior is not None else {}
        for attr, needed in _granted(block):
            # object-level rights already cover every attribute of the object
            before = previous.get(attr, NO_RIGHTS).union(previous.get("", NO_RIGHTS))
            if needed.issubset(before):
                continue
            held = delegable(at, block.object, attr)
            if subtree:
                held = held.intersection(delegable(at, block.object, attr, below=True))
            if not needed.issubset(held):
                label = f"{block.object}#{attr}" if attr else block.object
                text = f"{label}:{needed.canonical()}"
                if text not in missing:
                    missing.append(text)
    return missing


def missing_role_rights(
    directory: DirectoryClient,
    role_dn: str,
    *,
    at: str,
    delegable: Delegable,
    subtree: bool = False,
) -> list[str]:
    """Rights the role grants at ``at`` that the caller cannot grant (see :func:`_unheld`).

    Empty means assigning the role there grants nothing the caller does not hold.
    """
    return _unheld(role_blocks(directory, role_dn), at=at, subtree=subtree, delegable=delegable)


def assignment_identity(parsed: AclAssignment) -> tuple[object, ...]:
    """What an assignment grants, ignoring its position (a renumbering is not a change)."""
    return (
        parsed.scope,
        dnlib.normalize(parsed.role_dn),
        tuple("*" if m == ALL_USERS else dnlib.normalize(m) for m in parsed.members),
        parsed.user_filter,
        parsed.target_filter,
    )


def new_assignments(stored: Sequence[str], saved: Sequence[str]) -> list[AclAssignment]:
    """Assignments of ``saved`` that are new or changed relative to ``stored``.

    Identity ignores the index, so renumbering an assignment grants nothing new. Values
    that cannot be parsed are skipped: they grant nothing the engine evaluates.
    """
    known = {
        assignment_identity(parsed)
        for raw in stored
        if isinstance(parsed := parse_assignment(raw), AclAssignment)
    }
    added: list[AclAssignment] = []
    for raw in saved:
        parsed = parse_assignment(raw)
        if isinstance(parsed, AclAssignment) and assignment_identity(parsed) not in known:
            added.append(parsed)
    return added


def unheld_grants(
    directory: DirectoryClient,
    stored: Sequence[str],
    saved: Sequence[str],
    *,
    at: str,
    delegable: Delegable,
) -> list[str]:
    """``<object key>:<rights>`` of new or changed assignments granting more than the caller can.

    ``stored`` are the assignment values already on the entry, ``saved`` the ones about to
    replace them. Each new or changed assignment must be a subset of what the caller may
    grant at ``at`` (and below it for a subtree assignment); removed ones are always allowed.
    """
    missing: list[str] = []
    for parsed in new_assignments(stored, saved):
        for block in missing_role_rights(
            directory,
            parsed.role_dn,
            at=at,
            delegable=delegable,
            subtree=parsed.scope is AclScope.SUBTREE,
        ):
            if block not in missing:
                missing.append(block)
    return missing


def unheld_template_grants(
    directory: DirectoryClient,
    role_dn: str,
    stored: Sequence[str],
    saved: Sequence[str],
    *,
    delegable: Delegable,
) -> list[str]:
    """Rights a role template change adds where the role is assigned, that the caller cannot grant.

    Changing a role changes what every existing assignment of it grants, so each right
    the ``saved`` templates add over the ``stored`` ones must be grantable by the caller
    at every entry assigning the role. A role assigned nowhere grants nothing yet: its
    assignments are checked when they are made.
    """
    previous = _merged_blocks(stored)
    added = list(_merged_blocks(saved).values())
    target = dnlib.normalize(role_dn)
    missing: list[str] = []
    for entry in _assignment_entries(directory):
        for value in entry.values:
            parsed = parse_assignment(value)
            if not isinstance(parsed, AclAssignment) or dnlib.normalize(parsed.role_dn) != target:
                continue
            for block in _unheld(
                added,
                at=entry.dn,
                subtree=parsed.scope is AclScope.SUBTREE,
                delegable=delegable,
                already=previous,
            ):
                if block not in missing:
                    missing.append(block)
    return missing


def encode_member(dn: str) -> str:
    """Base64 form of a member as stored (exposed for tests and the health checks)."""
    return base64.b64encode(dn.encode("utf-8")).decode("ascii")


__all__ = [
    "AclAdminError",
    "Delegable",
    "RightsReport",
    "RoleInUseError",
    "RoleInfo",
    "UnheldRightsError",
    "all_assignments",
    "assignment_from_json",
    "assignment_identity",
    "assignment_to_json",
    "assignments_using_role",
    "check_department",
    "check_rights",
    "check_role_name",
    "create_role",
    "delete_role",
    "encode_member",
    "get_role",
    "grants_everything",
    "list_assignments",
    "list_roles",
    "missing_role_rights",
    "new_assignments",
    "reorder",
    "role_blocks",
    "role_container",
    "set_assignments",
    "template_from_json",
    "template_to_json",
    "unheld_grants",
    "unheld_template_grants",
    "update_role",
]
