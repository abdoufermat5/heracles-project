"""Directory health: checks (with optional fixes) for new or migrated directories.

Every check returns a :class:`CheckResult` (status, English message, stable ``message_key`` with
its ``message_params``, offending DNs, whether a fix exists). Fixes only touch the DNs they are
given and report what they did.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

import structlog

from heracles.acl import admin as acl_admin
from heracles.acl.model import AclAssignment, AclScope, Ignored
from heracles.acl.parser import parse_assignment, serialise_assignment
from heracles.core.config_store import RuntimeConfig, effective_settings
from heracles.core.containers import ensure_container
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
    SizeLimitExceededError,
)
from heracles.ldap.config import DirectoryConfig
from heracles.ldap.filter import escape_filter_value
from heracles.schema import names as schema

log = structlog.get_logger(__name__)

type Status = Literal["ok", "warning", "error"]

_OC = schema.OC
_STD = schema.STD_OC

#: Default ACL roles: ``(cn, description, template value)``.
DEFAULT_ROLES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "manager",
        "Manage all users of the branch",
        "0:user/user;cmdrw,user/posixAccount;cmdrw",
    ),
    (
        "editowninfos",
        "Users edit their own information",
        "0:user/user;srw,user/posixAccount;srw",
    ),
    (
        "editownpwd",
        "Users edit their own password",
        "0:user/user;s#userPassword;rw",
    ),
)
SUPER_ADMIN_ROLE = ("admin", "Full rights on the whole directory", "0:all;cmdrw")

_CONTAINER_NAMES: Final = frozenset(
    {
        "people",
        "groups",
        "roles",
        "aclroles",
        "systems",
        "servers",
        "workstations",
        "terminals",
        "printers",
        "phones",
        "netdevices",
        "mobile",
        "sudoers",
        "dsa",
        "alias",
        "apps",
        "dns",
        "dhcp",
        "audit",
        "tasks",
        "locks",
        "tokens",
        "recovery",
        "snapshots",
        schema.APP_OU.split("=", 1)[1],  # application container, e.g. "heracles"
        "mail",
        "netgroups",
        "automount",
        "archive",
        "restricted",
        "ipam",
        "templates",
    }
)


#: Outcomes of a check message: the second segment of ``message_key`` (``<check id>.<outcome>``).
#: ``ok`` when nothing is wrong; the others say what is (see :data:`CHECK_MESSAGE_PARAMS` for
#: the parameters each one carries).
MESSAGE_OUTCOMES: Final = (
    "ok",
    "missing",
    "unmarked",
    "unwritable",
    "plaintext",
    "found",
    "bootstrap_only",
    "misplaced",
    "duplicates",
    "failed",
)

#: Parameters interpolated in the localised message of every outcome (the English ``message``
#: stays the fallback). Values are JSON scalars or lists of strings.
CHECK_MESSAGE_PARAMS: Final[Mapping[str, tuple[str, ...]]] = {
    "root_object.missing": ("dn",),
    "root_object.unmarked": ("dn",),
    "root_object.ok": (),
    "bind_write.missing": ("dn",),
    "bind_write.unwritable": ("dn",),
    "bind_write.ok": (),
    "transport.plaintext": ("uris",),
    "transport.ok": (),
    "hidden_users.found": ("count",),
    "hidden_users.ok": (),
    "super_admin.ok": ("count",),
    "super_admin.bootstrap_only": (),
    "super_admin.missing": (),
    "default_roles.missing": ("count", "roles"),
    "default_roles.ok": (),
    "users_tree.misplaced": ("count", "noun", "rdn"),
    "users_tree.ok": ("noun", "rdn"),
    "groups_tree.misplaced": ("count", "noun", "rdn"),
    "groups_tree.ok": ("noun", "rdn"),
    "posix_groups_tree.misplaced": ("count", "noun", "rdn"),
    "posix_groups_tree.ok": ("noun", "rdn"),
    "departments.unmarked": ("count",),
    "departments.ok": (),
    "duplicate_ids.duplicates": ("uids", "gids"),
    "duplicate_ids.ok": (),
    "plugin_data.found": ("plugins", "count"),
    "plugin_data.ok": (),
}
"""Parameters of every message key produced by :data:`CHECKS` (``<check id>.failed`` takes
``error``)."""


@dataclass(slots=True)
class CheckResult:
    id: str
    status: Status
    #: English fallback; the client renders ``message_key`` with ``message_params``.
    message: str
    dns: list[str] = field(default_factory=lambda: [])
    #: A fix exists (``fix`` can be called for this check).
    fixable: bool = False
    #: Names of extra options the fix needs (``uid``, ``dn``, ...).
    options: list[str] = field(default_factory=lambda: [])
    #: Stable, language-neutral identifier of the message: ``<check id>.<outcome>``.
    message_key: str = ""
    #: Values interpolated in the localised message (JSON scalars or lists of strings).
    message_params: dict[str, Any] = field(default_factory=lambda: {})

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "dns": self.dns,
            "fixable": self.fixable,
            "options": self.options,
            "message_key": self.message_key,
            "message_params": self.message_params,
        }


@dataclass(slots=True)
class FixResult:
    id: str
    fixed: list[str] = field(default_factory=lambda: [])
    failed: dict[str, str] = field(default_factory=lambda: {})
    message: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fixed": self.fixed,
            "failed": self.failed,
            "message": self.message,
        }


@dataclass(slots=True)
class CheckContext:
    directory: DirectoryClient
    config: RuntimeConfig
    #: Normalised DNs of the bootstrap administrators (outside the directory ACLs).
    bootstrap_admins: frozenset[str] = frozenset()
    #: ``(plugin name, required objectClasses)`` of the plugins that are available in the
    #: schema but switched off.
    disabled_plugins: Sequence[tuple[str, Sequence[str]]] = ()
    #: ``ldap://`` endpoints without StartTLS: credentials travel in clear text.
    plaintext_uris: Sequence[str] = ()

    @property
    def base(self) -> str:
        return self.directory.base_dn

    def search(
        self,
        filterstr: str,
        attrs: Sequence[str] | None = None,
        base: str | None = None,
        scope: Scope = Scope.SUBTREE,
    ) -> Iterator[Entry]:
        try:
            yield from self.directory.search(base or self.base, filterstr, scope, attrs)
        except NoSuchObjectError:
            return

    @property
    def users_rdn(self) -> str:
        return self.config.user_rdn

    @property
    def groups_rdn(self) -> str:
        return self.config.group_rdn

    @property
    def roles_rdn(self) -> str:
        return self.config.acl_role_rdn


def plaintext_uris(config: DirectoryConfig) -> list[str]:
    """``ldap://`` servers of a directory that are not upgraded with StartTLS."""
    if config.starttls:
        return []
    return [u for u in config.all_uris if u.lower().startswith("ldap://")]


def insecure_uris(directory: object) -> list[str]:
    """Plaintext endpoints of a directory client (empty for one without settings)."""
    config = getattr(directory, "config", None)
    return plaintext_uris(config) if isinstance(config, DirectoryConfig) else []


def context_for(
    directory: DirectoryClient,
    bootstrap_admins: Sequence[str] = (),
    disabled_plugins: Sequence[tuple[str, Sequence[str]]] = (),
    plaintext_uris: Sequence[str] | None = None,
) -> CheckContext:
    return CheckContext(
        directory,
        effective_settings(directory),
        frozenset(dnlib.normalize(d) for d in bootstrap_admins),
        disabled_plugins,
        tuple(plaintext_uris if plaintext_uris is not None else insecure_uris(directory)),
    )


# ------------------------------------------------------------------ helpers


def _is_marked(entry: Entry) -> bool:
    return entry.has_object_class(_OC.DEPARTMENT)


def _department_of(ctx: CheckContext, dn: str) -> str:
    """Nearest ancestor that is a department (or the base)."""
    parent = dnlib.parent(dn)
    while parent is not None and dnlib.is_descendant(parent, ctx.base, include_self=False):
        entry = ctx.directory.get(parent, ["objectClass"])
        if entry is not None and _is_marked(entry):
            return parent
        parent = dnlib.parent(parent)
    return ctx.base


def _rdn_value(dn: str) -> str:
    return dnlib.unescape_rdn_value(dnlib.strip_rdn(dnlib.rdn(dn).partition("=")[2]))


def _in_container(dn: str, container_rdn: str) -> bool:
    parent = dnlib.parent(dn)
    if parent is None:
        return False
    return dnlib.normalize(parent).startswith(dnlib.normalize(container_rdn) + ",")


def _add_classes(directory: DirectoryClient, entry: Entry, classes: Sequence[str]) -> None:
    missing = [c for c in classes if not entry.has_object_class(c)]
    if missing:
        directory.modify(
            entry.dn, [Modification("add", "objectClass", [c.encode() for c in missing])]
        )


_REFERENCE_ATTRS = ("member", "uniqueMember", "roleOccupant", "owner", "manager", "seeAlso")


def _renamed_assignments(values: Sequence[str], target: str, new: str) -> list[str] | None:
    """ACL assignment values with ``target`` (a normalised DN) replaced by ``new``.

    ``None`` when no value refers to it; values that do not parse are kept untouched.
    """
    out: list[str] = []
    changed = False
    for value in values:
        parsed = parse_assignment(value)
        if isinstance(parsed, AclAssignment) and target in {
            dnlib.normalize(d) for d in (parsed.role_dn, *parsed.members) if d != "*"
        }:
            role = new if dnlib.normalize(parsed.role_dn) == target else parsed.role_dn
            members = tuple(
                new if m != "*" and dnlib.normalize(m) == target else m for m in parsed.members
            )
            value = serialise_assignment(replace(parsed, role_dn=role, members=members))
            changed = True
        out.append(value)
    return out if changed else None


def _propagate_rename(directory: DirectoryClient, old: str, new: str, base: str) -> None:
    """Rewrite references to ``old`` in the usual DN-valued attributes and ACL assignments."""
    quoted = escape_filter_value(old)
    acl_attr = schema.ATTR.ACL_ENTRY
    clauses = [f"({a}={quoted})" for a in _REFERENCE_ATTRS]
    clauses.append(f"({acl_attr}=*)")  # DNs are encoded inside the assignment values
    try:
        holders = list(
            directory.search(
                base, "(|" + "".join(clauses) + ")", Scope.SUBTREE, [*_REFERENCE_ATTRS, acl_attr]
            )
        )
    except DirectoryError as exc:
        log.warning("rename_references_not_updated", dn=old, error=type(exc).__name__)
        return
    target = dnlib.normalize(old)
    for holder in holders:
        mods: list[Modification] = []
        for attr in _REFERENCE_ATTRS:
            values = holder.texts(attr)
            if any(dnlib.normalize(v) == target for v in values):
                rewritten = [new if dnlib.normalize(v) == target else v for v in values]
                mods.append(Modification("replace", attr, [v.encode() for v in rewritten]))
        assignments = _renamed_assignments(holder.texts(acl_attr), target, new)
        if assignments is not None:
            mods.append(Modification("replace", acl_attr, [v.encode() for v in assignments]))
        if mods:
            directory.modify(holder.dn, mods)


def _move(ctx: CheckContext, dn: str, container_rdn: str) -> str:
    """Move ``dn`` into ``<container_rdn>,<its department>``; returns the new DN."""
    department = _department_of(ctx, dn)
    container = dnlib.join(container_rdn, department)
    ensure_container(ctx.directory, container)
    new = ctx.directory.rename(dn, dnlib.rdn(dn), container)
    _propagate_rename(ctx.directory, dn, new, ctx.base)
    return new


# -------------------------------------------------------------------- checks


def check_root(ctx: CheckContext) -> CheckResult:
    entry = ctx.directory.get(ctx.base)
    if entry is None:
        return CheckResult(
            "root_object",
            "error",
            "The base entry does not exist.",
            [ctx.base],
            message_key="root_object.missing",
            message_params={"dn": ctx.base},
        )
    if not _is_marked(entry):
        return CheckResult(
            "root_object",
            "warning",
            "The base entry is not marked as a department.",
            [ctx.base],
            fixable=True,
            message_key="root_object.unmarked",
            message_params={"dn": ctx.base},
        )
    return CheckResult(
        "root_object", "ok", "The base entry is correctly set up.", message_key="root_object.ok"
    )


def fix_root(ctx: CheckContext, dns: Sequence[str], options: Mapping[str, str]) -> FixResult:
    del dns, options
    result = FixResult("root_object")
    entry = ctx.directory.get(ctx.base)
    if entry is None:
        result.failed[ctx.base] = "The base entry does not exist."
        return result
    mods: list[Modification] = []
    if not entry.has_object_class(_OC.DEPARTMENT):
        mods.append(Modification("add", "objectClass", [_OC.DEPARTMENT.encode()]))
    name = _rdn_value(ctx.base)
    if not entry.get("ou"):
        mods.append(Modification("add", "ou", [name.encode()]))
    if not entry.get("description"):
        mods.append(Modification("add", "description", [(entry.text("o") or name).encode()]))
    try:
        ctx.directory.modify(ctx.base, mods)
        result.fixed.append(ctx.base)
    except DirectoryError as exc:
        result.failed[ctx.base] = type(exc).__name__
    return result


def check_bind_write(ctx: CheckContext) -> CheckResult:
    entry = ctx.directory.get(ctx.base)
    if entry is None:
        return CheckResult(
            "bind_write",
            "error",
            "The base entry does not exist.",
            [ctx.base],
            message_key="bind_write.missing",
            message_params={"dn": ctx.base},
        )
    try:
        description = entry.get("description")
        if description:
            ctx.directory.modify(ctx.base, [Modification("replace", "description", description)])
        else:
            ctx.directory.modify(ctx.base, [Modification("add", "description", [b"write test"])])
            ctx.directory.modify(ctx.base, [Modification("delete", "description")])
    except DirectoryError:
        return CheckResult(
            "bind_write",
            "error",
            "The directory account cannot write to the base entry.",
            message_key="bind_write.unwritable",
            message_params={"dn": ctx.base},
        )
    return CheckResult(
        "bind_write", "ok", "The directory account can write.", message_key="bind_write.ok"
    )


def check_transport(ctx: CheckContext) -> CheckResult:
    if not ctx.plaintext_uris:
        return CheckResult(
            "transport", "ok", "The directory connection is encrypted.", message_key="transport.ok"
        )
    return CheckResult(
        "transport",
        "warning",
        "The directory connection uses ldap:// without StartTLS: the bind password and "
        "every password sent through the console travel unencrypted ("
        + ", ".join(ctx.plaintext_uris)
        + "). Use ldaps:// or enable StartTLS.",
        message_key="transport.plaintext",
        message_params={"uris": list(ctx.plaintext_uris)},
    )


_PERSON_CLASSES = (_STD.INET_ORG_PERSON, _STD.ORGANIZATIONAL_PERSON, _STD.PERSON)


def _hidden_accounts(ctx: CheckContext) -> list[Entry]:
    flt = (
        f"(&(|(objectClass={_STD.POSIX_ACCOUNT})(objectClass={_STD.SHADOW_ACCOUNT})"
        f"(objectClass={_STD.PERSON})(objectClass={_STD.ORGANIZATIONAL_PERSON}))"
        f"(!(objectClass={_STD.INET_ORG_PERSON}))(uid=*))"
    )
    return list(ctx.search(flt, ["objectClass", "sn", "cn", "uid"]))


def check_hidden_users(ctx: CheckContext) -> CheckResult:
    found = _hidden_accounts(ctx)
    if not found:
        return CheckResult(
            "hidden_users", "ok", "Every account is visible.", message_key="hidden_users.ok"
        )
    return CheckResult(
        "hidden_users",
        "warning",
        f"{len(found)} account(s) lack the person classes and are not listed as users.",
        [e.dn for e in found],
        fixable=True,
        message_key="hidden_users.found",
        message_params={"count": len(found)},
    )


def fix_hidden_users(
    ctx: CheckContext, dns: Sequence[str], options: Mapping[str, str]
) -> FixResult:
    del options
    result = FixResult("hidden_users")
    wanted = {dnlib.normalize(d) for d in dns}
    for entry in _hidden_accounts(ctx):
        if wanted and dnlib.normalize(entry.dn) not in wanted:
            continue
        if not (entry.get("sn") and entry.get("cn")):
            result.failed[entry.dn] = "The entry has no surname or common name."
            continue
        try:
            _add_classes(ctx.directory, entry, _PERSON_CLASSES)
            result.fixed.append(entry.dn)
        except DirectoryError as exc:
            result.failed[entry.dn] = type(exc).__name__
    return result


def _roles_granting_everything(ctx: CheckContext) -> set[str]:
    return {
        dnlib.normalize(r.dn)
        for r in acl_admin.list_roles(ctx.directory)
        if acl_admin.grants_everything(r.templates)
    }


def _super_assignments(ctx: CheckContext) -> list[tuple[str, AclAssignment]]:
    roles = _roles_granting_everything(ctx)
    out: list[tuple[str, AclAssignment]] = []
    for entry in ctx.search(f"(objectClass={_OC.ACL_ASSIGNMENT})", [schema.ATTR.ACL_ENTRY]):
        for value in entry.texts(schema.ATTR.ACL_ENTRY):
            parsed = parse_assignment(value)
            if (
                not isinstance(parsed, Ignored)
                and parsed.members
                and dnlib.normalize(parsed.role_dn) in roles
                and parsed.user_filter is None
                and parsed.target_filter is None
            ):
                out.append((entry.dn, parsed))
    return out


def check_super_admin(ctx: CheckContext) -> CheckResult:
    found = _super_assignments(ctx)
    if found:
        return CheckResult(
            "super_admin",
            "ok",
            f"{len(found)} assignment(s) grant full rights.",
            message_key="super_admin.ok",
            message_params={"count": len(found)},
        )
    if ctx.bootstrap_admins:
        return CheckResult(
            "super_admin",
            "warning",
            "Only the bootstrap administrators from the configuration have full rights.",
            fixable=True,
            options=["dn"],
            message_key="super_admin.bootstrap_only",
        )
    return CheckResult(
        "super_admin",
        "error",
        "Nobody has full rights on the directory.",
        fixable=True,
        options=["dn"],
        message_key="super_admin.missing",
    )


def _ensure_role(ctx: CheckContext, cn: str, description: str, template: str) -> str:
    container = acl_admin.role_container(ctx.directory, None, ctx.roles_rdn)
    dn = f"cn={dnlib.escape_rdn_value(cn)},{container}"
    if ctx.directory.get(dn) is not None:
        return dn
    ensure_container(ctx.directory, container)
    ctx.directory.add(
        dn,
        {
            "objectClass": [_OC.ACL_ROLE.encode()],
            "cn": [cn.encode()],
            "description": [description.encode()],
            schema.ATTR.ACL_TEMPLATE: [template.encode()],
        },
    )
    return dn


def _add_base_assignment(ctx: CheckContext, role_dn: str, member_dn: str) -> None:
    entry = ctx.directory.get(ctx.base, ["objectClass", schema.ATTR.ACL_ENTRY])
    assert entry is not None
    existing = entry.texts(schema.ATTR.ACL_ENTRY)
    indices = [
        p.index for p in (parse_assignment(v) for v in existing) if isinstance(p, AclAssignment)
    ]
    value = serialise_assignment(
        AclAssignment(max(indices, default=-1) + 1, AclScope.SUBTREE, role_dn, (member_dn,))
    )
    mods: list[Modification] = []
    if not entry.has_object_class(_OC.ACL_ASSIGNMENT):
        mods.append(Modification("add", "objectClass", [_OC.ACL_ASSIGNMENT.encode()]))
    mods.append(Modification("add", schema.ATTR.ACL_ENTRY, [value.encode()]))
    ctx.directory.modify(ctx.base, mods)


def fix_super_admin(ctx: CheckContext, dns: Sequence[str], options: Mapping[str, str]) -> FixResult:
    del dns
    result = FixResult("super_admin")
    user = options.get("dn", "").strip()
    try:
        exists = bool(user) and ctx.directory.get(user) is not None
    except DirectoryError:  # not a valid DN
        exists = False
    if not exists:
        result.failed[user or "dn"] = "Choose an existing user."
        return result
    try:
        role = _ensure_role(ctx, *SUPER_ADMIN_ROLE)
        _add_base_assignment(ctx, role, user)
        result.fixed.append(user)
    except DirectoryError as exc:
        result.failed[user] = type(exc).__name__
    return result


def create_admin_user(
    ctx: CheckContext,
    uid: str,
    *,
    password_hash: str,
    given_name: str = "Administrator",
    surname: str = "Admin",
    mail: str = "",
) -> str:
    """Create a user in the base people container with full rights; returns its DN."""
    container = dnlib.join(ctx.users_rdn, ctx.base)
    ensure_container(ctx.directory, container)
    dn = f"uid={dnlib.escape_rdn_value(uid)},{container}"
    attrs: dict[str, list[bytes]] = {
        "objectClass": [c.encode() for c in _PERSON_CLASSES],
        "uid": [uid.encode()],
        "cn": [f"{given_name} {surname}".encode()],
        "givenName": [given_name.encode()],
        "sn": [surname.encode()],
        "userPassword": [password_hash.encode()],
    }
    if mail:
        attrs["mail"] = [mail.encode()]
    try:
        ctx.directory.add(dn, attrs)
    except AlreadyExistsError:
        raise DirectoryError(f"{dn} already exists") from None
    role = _ensure_role(ctx, *SUPER_ADMIN_ROLE)
    _add_base_assignment(ctx, role, dn)
    return dn


def check_default_roles(ctx: CheckContext) -> CheckResult:
    present = {r.cn.lower() for r in acl_admin.list_roles(ctx.directory)}
    missing = [cn for cn, _d, _t in DEFAULT_ROLES if cn.lower() not in present]
    if not missing:
        return CheckResult(
            "default_roles", "ok", "The default roles exist.", message_key="default_roles.ok"
        )
    container = acl_admin.role_container(ctx.directory, None, ctx.roles_rdn)
    return CheckResult(
        "default_roles",
        "warning",
        f"Missing default roles: {', '.join(missing)}.",
        [f"cn={cn},{container}" for cn in missing],
        fixable=True,
        message_key="default_roles.missing",
        message_params={"count": len(missing), "roles": missing},
    )


def fix_default_roles(
    ctx: CheckContext, dns: Sequence[str], options: Mapping[str, str]
) -> FixResult:
    del options
    result = FixResult("default_roles")
    wanted = {dnlib.normalize(d) for d in dns}
    present = {r.cn.lower() for r in acl_admin.list_roles(ctx.directory)}
    container = acl_admin.role_container(ctx.directory, None, ctx.roles_rdn)
    for cn, description, template in DEFAULT_ROLES:
        dn = f"cn={cn},{container}"
        if cn.lower() in present or (wanted and dnlib.normalize(dn) not in wanted):
            continue
        try:
            _ensure_role(ctx, cn, description, template)
            result.fixed.append(dn)
        except DirectoryError as exc:
            result.failed[dn] = type(exc).__name__
    return result


def _misplaced(ctx: CheckContext, flt: str, container_rdn: str) -> list[str]:
    return [
        e.dn
        for e in ctx.search(flt, ["1.1"])
        if not _in_container(e.dn, container_rdn)
        and not dnlib.normalize(e.dn).endswith(
            ",ou=" + schema.APP_OU.partition("=")[2].lower() + "," + dnlib.normalize(ctx.base)
        )
    ]


def _check_misplaced(
    ctx: CheckContext, check_id: str, flt: str, container_rdn: str, noun: str
) -> CheckResult:
    found = _misplaced(ctx, flt, container_rdn)
    if not found:
        return CheckResult(
            check_id,
            "ok",
            f"Every {noun} is in the {container_rdn} tree.",
            message_key=f"{check_id}.ok",
            message_params={"noun": noun, "rdn": container_rdn},
        )
    return CheckResult(
        check_id,
        "warning",
        f"{len(found)} {noun}(s) are outside the {container_rdn} tree.",
        found,
        fixable=True,
        message_key=f"{check_id}.misplaced",
        message_params={"count": len(found), "noun": noun, "rdn": container_rdn},
    )


def _fix_misplaced(
    ctx: CheckContext, check_id: str, flt: str, container_rdn: str, dns: Sequence[str]
) -> FixResult:
    result = FixResult(check_id)
    wanted = {dnlib.normalize(d) for d in dns}
    for dn in _misplaced(ctx, flt, container_rdn):
        if wanted and dnlib.normalize(dn) not in wanted:
            continue
        try:
            result.fixed.append(_move(ctx, dn, container_rdn))
        except DirectoryError as exc:
            result.failed[dn] = type(exc).__name__
    return result


def _users_filter() -> str:
    return f"(objectClass={_STD.INET_ORG_PERSON})"


def _groups_filter() -> str:
    return f"(&(objectClass={_STD.GROUP_OF_NAMES})(!(objectClass={_STD.POSIX_GROUP})))"


def _posix_groups_filter() -> str:
    return f"(objectClass={_STD.POSIX_GROUP})"


def check_users_tree(ctx: CheckContext) -> CheckResult:
    return _check_misplaced(ctx, "users_tree", _users_filter(), ctx.users_rdn, "user")


def check_groups_tree(ctx: CheckContext) -> CheckResult:
    return _check_misplaced(ctx, "groups_tree", _groups_filter(), ctx.groups_rdn, "group")


def check_posix_groups_tree(ctx: CheckContext) -> CheckResult:
    return _check_misplaced(
        ctx, "posix_groups_tree", _posix_groups_filter(), ctx.groups_rdn, "POSIX group"
    )


def _unmarked_departments(ctx: CheckContext) -> list[Entry]:
    flt = f"(&(objectClass={_STD.ORGANIZATIONAL_UNIT})(!(objectClass={_OC.DEPARTMENT})))"
    out: list[Entry] = []
    for entry in ctx.search(flt, ["objectClass", "ou", "description"]):
        if dnlib.normalize(entry.dn) == dnlib.normalize(ctx.base):
            continue
        name = (entry.text("ou") or _rdn_value(entry.dn)).lower()
        if name in _CONTAINER_NAMES:
            continue
        parent = dnlib.parent(entry.dn)
        if parent is None:
            continue
        if dnlib.normalize(parent) != dnlib.normalize(ctx.base):
            parent_entry = ctx.directory.get(parent, ["objectClass"])
            if parent_entry is None or not _is_marked(parent_entry):
                continue
        out.append(entry)
    return out


def check_departments(ctx: CheckContext) -> CheckResult:
    found = _unmarked_departments(ctx)
    if not found:
        return CheckResult(
            "departments", "ok", "Every department is visible.", message_key="departments.ok"
        )
    return CheckResult(
        "departments",
        "warning",
        f"{len(found)} organizational unit(s) are not marked as departments.",
        [e.dn for e in found],
        fixable=True,
        message_key="departments.unmarked",
        message_params={"count": len(found)},
    )


def fix_departments(ctx: CheckContext, dns: Sequence[str], options: Mapping[str, str]) -> FixResult:
    del options
    result = FixResult("departments")
    wanted = {dnlib.normalize(d) for d in dns}
    for entry in _unmarked_departments(ctx):
        if wanted and dnlib.normalize(entry.dn) not in wanted:
            continue
        mods = [Modification("add", "objectClass", [_OC.DEPARTMENT.encode()])]
        if not entry.get("description"):
            name = entry.text("ou") or _rdn_value(entry.dn)
            mods.append(Modification("add", "description", [name.encode()]))
        try:
            ctx.directory.modify(entry.dn, mods)
            result.fixed.append(entry.dn)
        except DirectoryError as exc:
            result.failed[entry.dn] = type(exc).__name__
    return result


def _duplicates(ctx: CheckContext, object_class: str, attr: str) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for entry in ctx.search(f"(objectClass={object_class})", [attr]):
        value = entry.text(attr)
        if value:
            seen.setdefault(value, []).append(entry.dn)
    return {v: dns for v, dns in seen.items() if len(dns) > 1}


def check_duplicate_ids(ctx: CheckContext) -> CheckResult:
    uids = _duplicates(ctx, _STD.POSIX_ACCOUNT, "uidNumber")
    gids = _duplicates(ctx, _STD.POSIX_GROUP, "gidNumber")
    if not uids and not gids:
        return CheckResult(
            "duplicate_ids",
            "ok",
            "No duplicated numeric identifier.",
            message_key="duplicate_ids.ok",
        )
    dns = sorted({d for group in (*uids.values(), *gids.values()) for d in group})
    parts: list[str] = []
    if uids:
        parts.append("uidNumber " + ", ".join(sorted(uids)))
    if gids:
        parts.append("gidNumber " + ", ".join(sorted(gids)))
    return CheckResult(
        "duplicate_ids",
        "warning",
        "Duplicated identifiers: " + "; ".join(parts) + ".",
        dns,
        message_key="duplicate_ids.duplicates",
        message_params={"uids": sorted(uids), "gids": sorted(gids)},
    )


#: Entries counted per disabled plugin (more is reported as "at least").
PLUGIN_DATA_LIMIT: Final = 1000


def _plugin_entry_count(ctx: CheckContext, classes: Sequence[str]) -> tuple[int, bool]:
    """``(count, truncated)`` of the entries using any of ``classes`` (size-bounded)."""
    terms = "".join(f"(objectClass={escape_filter_value(c)})" for c in classes)
    flt = f"(|{terms})" if len(classes) > 1 else terms
    count = 0
    try:
        for _entry in ctx.directory.search(
            ctx.base, flt, Scope.SUBTREE, ["1.1"], size_limit=PLUGIN_DATA_LIMIT
        ):
            count += 1
    except NoSuchObjectError:
        return 0, False
    except SizeLimitExceededError:
        return PLUGIN_DATA_LIMIT, True
    return count, False


def check_plugin_data(ctx: CheckContext) -> CheckResult:
    """Entries that use the classes of a plugin switched off (its tabs are hidden)."""
    found: list[str] = []
    plugins: list[str] = []
    count = 0
    for name, classes in ctx.disabled_plugins:
        if not classes:
            continue
        entries, truncated = _plugin_entry_count(ctx, classes)
        if entries:
            plugins.append(name)
            count += entries
            found.append(f"{name} ({'at least ' if truncated else ''}{entries})")
    if not found:
        return CheckResult(
            "plugin_data",
            "ok",
            "No data belongs to a disabled plugin.",
            message_key="plugin_data.ok",
        )
    return CheckResult(
        "plugin_data",
        "warning",
        "Entries use the schema of disabled plugins, which hides them in the console: "
        + ", ".join(found)
        + ".",
        message_key="plugin_data.found",
        message_params={"plugins": plugins, "count": count},
    )


type CheckFn = Callable[[CheckContext], CheckResult]
type FixFn = Callable[[CheckContext, Sequence[str], Mapping[str, str]], FixResult]

CHECKS: Final[tuple[tuple[str, CheckFn, FixFn | None], ...]] = (
    ("root_object", check_root, fix_root),
    ("bind_write", check_bind_write, None),
    ("transport", check_transport, None),
    ("hidden_users", check_hidden_users, fix_hidden_users),
    ("super_admin", check_super_admin, fix_super_admin),
    ("default_roles", check_default_roles, fix_default_roles),
    (
        "users_tree",
        check_users_tree,
        lambda c, d, o: _fix_misplaced(c, "users_tree", _users_filter(), c.users_rdn, d),
    ),
    (
        "groups_tree",
        check_groups_tree,
        lambda c, d, o: _fix_misplaced(c, "groups_tree", _groups_filter(), c.groups_rdn, d),
    ),
    (
        "posix_groups_tree",
        check_posix_groups_tree,
        lambda c, d, o: _fix_misplaced(
            c, "posix_groups_tree", _posix_groups_filter(), c.groups_rdn, d
        ),
    ),
    ("departments", check_departments, fix_departments),
    ("duplicate_ids", check_duplicate_ids, None),
    ("plugin_data", check_plugin_data, None),
)
CHECK_IDS: Final = tuple(c[0] for c in CHECKS)


class UnknownCheckError(KeyError):
    """No check has this identifier (or it has no fix)."""


def run_checks(ctx: CheckContext, only: Sequence[str] | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check_id, check, _fix in CHECKS:
        if only and check_id not in only:
            continue
        try:
            results.append(check(ctx))
        except DirectoryError as exc:
            log.warning("check_failed", check=check_id, error=type(exc).__name__)
            results.append(
                CheckResult(
                    check_id,
                    "error",
                    f"The check failed: {type(exc).__name__}.",
                    message_key=f"{check_id}.failed",
                    message_params={"error": type(exc).__name__},
                )
            )
    return results


def run_fix(
    ctx: CheckContext,
    check_id: str,
    dns: Sequence[str] = (),
    options: Mapping[str, str] | None = None,
) -> FixResult:
    for cid, _check, fix in CHECKS:
        if cid == check_id:
            if fix is None:
                raise UnknownCheckError(check_id)
            return fix(ctx, list(dns), options or {})
    raise UnknownCheckError(check_id)
