"""Administration API: ACL roles and assignments, configuration, triggers, health, plugins, tasks.

Mounted under ``/api/v2/admin`` by the administration plugin. Every endpoint checks the
rights of the connected user (bootstrap administrators have all rights).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager  # pyright: ignore[reportDeprecated]
from datetime import UTC, datetime
from importlib.metadata import entry_points
from typing import Any, cast

import structlog
from fastapi import APIRouter, FastAPI, Query, Response
from pydantic import BaseModel, Field

from heracles.acl import FULL_RIGHTS, NO_RIGHTS, Rights
from heracles.acl import admin as acl_admin
from heracles.acl.model import ALL_OBJECTS
from heracles.api.deps import CurrentUser, CurrentUserDep, StateDep
from heracles.api.domain import Domain, DomainDep, invalidate_acl_cache
from heracles.api.errors import ApiError, forbidden, not_found, validation
from heracles.api.settings import ApiSettings
from heracles.api.state import AppState
from heracles.core import config_store, setup_checks
from heracles.core.generalized_time import format_generalized_time, parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Modification, NoSuchObjectError, Scope
from heracles.objects.errors import UnknownTypeError
from heracles.objects.registry import PLUGIN_GROUP, Plugin, TypeRegistry
from heracles.schema import names as schema
from heracles.triggers import HOOK_MODES, TabHook, TriggerSettings, parse_hook

log = structlog.get_logger(__name__)

ROLE_KEY = "acl/aclRole"
ASSIGNMENT_KEY = "acl/aclAssignment"
CONFIG_KEY = "config/config"
"""ACL object keys guarding the administration screens (``rwcd`` rights)."""


# ------------------------------------------------------------------- access


def rights_of(user: CurrentUser, domain: Domain, key: str, dn: str | None = None) -> Rights:
    """Rights of the connected user on one administration object key."""
    if domain.is_admin(user.dn):
        return FULL_RIGHTS
    return domain.evaluator(user).permissions(dn or user.directory.base_dn, key)


def _require(
    user: CurrentUser, domain: Domain, key: str, letter: str, dn: str | None = None
) -> None:
    rights = rights_of(user, domain, key, dn)
    allowed = {
        "r": rights.read,
        "w": rights.write,
        "c": rights.create,
        "d": rights.delete,
    }[letter]
    if not allowed:
        raise forbidden("You do not have the rights for this operation")


def _audit(user: CurrentUser, domain: Domain, action: str, kind: str, dn: str, *notes: str) -> None:
    """Record an administration change in the audit log (no-op without the audit plugin)."""
    domain.audit.record_by(user, action, object_type=kind, object_dn=dn, attributes=notes)


@contextmanager  # pyright: ignore[reportDeprecated]
def admin_errors() -> Iterator[None]:
    try:
        yield
    except acl_admin.RoleInUseError as exc:
        raise ApiError(409, "conflict", "The role is still in use", fields=exc.fields) from exc
    except acl_admin.AclAdminError as exc:
        raise validation("Invalid data", exc.fields) from exc
    except config_store.ConfigError as exc:
        raise validation("Invalid configuration", exc.fields) from exc
    except NoSuchObjectError as exc:
        raise not_found(f"Object not found: {exc}") from exc


# ----------------------------------------------------------------- runtime


def yaml_defaults_of(settings: ApiSettings) -> config_store.YamlDefaults:
    """Bootstrap values taken from the YAML settings."""
    return config_store.YamlDefaults(
        login_attribute=settings.login.login_attribute,
        session_lifetime=settings.session.idle_timeout_seconds,
        password_default_hash=settings.password.default_method,
        password_allowed_hashes=list(settings.password.allowed_methods),
        force_password_default_hash=settings.password.force_default,
        password_min_length=settings.password.min_length,
        password_min_differ=settings.password.min_differing,
        http_header_auth_enabled=settings.login.header_enabled,
        http_header_name=settings.login.header_name,
        recovery_enabled=settings.recovery.enabled,
        recovery_validity=settings.recovery.ttl_minutes,
    )


def effective(state: AppState, directory_id: str) -> config_store.RuntimeConfig:
    config_store.set_yaml_defaults(yaml_defaults_of(state.settings))
    return config_store.effective_settings(state.directories[directory_id])


#: RDN defaults of the types whose container is configurable (captured before any override).
_ORIGINAL_RDN: dict[str, str] = {}

_RDN_KEYS = (
    ("user_rdn", "user"),
    ("group_rdn", "group"),
    ("acl_role_rdn", "acl_role"),
)


def apply_runtime(
    state: AppState,
    domain: Domain,
    directory_id: str,
    config: config_store.RuntimeConfig,
) -> None:
    """Make the running application follow ``config`` (no restart needed)."""
    from heracles.auth.login import LoginConfig
    from heracles.auth.sessions import InMemorySessionStore
    from heracles.auth.sessions_db import SqliteSessionStore

    policy = state.policy
    policy.min_length = config.password_min_length
    policy.min_differing = config.password_min_differ
    policy.default_method = config.password_default_hash
    policy.force_default = config.force_password_default_hash
    if config.password_allowed_hashes:
        policy.allowed_methods = tuple(config.password_allowed_hashes)
    login = LoginConfig(
        login_attribute=config.login_attribute,
        user_object_class=state.login_config.user_object_class,
    )
    state.login_config = login
    state.recovery.login_config = login
    if isinstance(state.sessions, InMemorySessionStore | SqliteSessionStore):
        state.sessions.idle_timeout = config.session_lifetime
    domain.acl_target_limit = config.acl_target_filter_limit

    stored = config.from_directory
    registry = domain.registry
    for key, type_name in _RDN_KEYS:
        with contextlib.suppress(UnknownTypeError):
            info = registry.get(type_name)
            original = _ORIGINAL_RDN.setdefault(type_name, info.type.rdn)
            info.type.rdn = str(config.get(key)) if key in stored else original
    if "snapshot_base" in stored and config.snapshot_base:
        directory = state.directories[directory_id]
        domain.snapshots(directory_id, directory).snapshot_base = config.snapshot_base
    posix = registry.settings.get("posix")
    if posix is not None:
        for key, attr in (
            ("shells", "shells"),
            ("default_shell", "default_shell"),
            ("uid_number_base", "uid_number_base"),
            ("gid_number_base", "gid_number_base"),
            ("min_id", "min_id"),
        ):
            if key in stored and hasattr(posix, attr):
                setattr(posix, attr, config.get(key))
    own = registry.settings.get("acl_admin")
    if isinstance(own, TriggerSettings):
        own.registry = registry
        own.location = directory_id


def refresh_runtime(app: FastAPI) -> None:
    """Re-read the configuration entry of the default directory and apply it."""
    state: AppState = app.state.heracles
    domain: Domain = app.state.domain
    directory_id = next(iter(state.directories), None)
    if directory_id is None:
        return
    config_store.invalidate(state.directories[directory_id])
    apply_runtime(state, domain, directory_id, effective(state, directory_id))


@asynccontextmanager
async def runtime_lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Apply the stored configuration at startup, then follow changes made elsewhere."""

    async def follow() -> None:
        while True:
            try:
                await asyncio.to_thread(refresh_runtime, app)
            except Exception:
                log.warning("runtime_config_refresh_failed", exc_info=True)
            await asyncio.sleep(config_store.CACHE_TTL_SECONDS)

    task = asyncio.create_task(follow())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ------------------------------------------------------------------ catalog


def build_catalog(registry: TypeRegistry) -> dict[str, Any]:
    """Object keys by category, for the rights matrix."""
    categories: dict[str, dict[str, Any]] = {}
    for info in registry.list():
        entry = categories.setdefault(
            info.acl_category,
            {
                "category": info.acl_category,
                "label": info.type.label_plural or info.type.label,
                "wildcard": f"{info.acl_category}/0",
                "objects": [],
            },
        )
        known = {o["key"] for o in entry["objects"]}
        for tab in info.tabs:
            key = info.acl_object(tab)
            if key in known:
                continue
            known.add(key)
            entry["objects"].append(
                {
                    "key": key,
                    "label": tab.display_label(),
                    "type": info.type.name,
                    "attributes": [
                        {"name": a.name, "label": a.label}
                        for a in tab.attributes()
                        if a.kind not in ("hidden", "display") and a.stored
                    ],
                }
            )
    categories.setdefault(
        "config",
        {
            "category": "config",
            "label": "Configuration",
            "wildcard": "config/0",
            "objects": [
                {"key": CONFIG_KEY, "label": "Configuration", "type": "", "attributes": []}
            ],
        },
    )
    return {"all": ALL_OBJECTS, "categories": list(categories.values())}


def tab_keys(registry: TypeRegistry) -> list[str]:
    """Distinct tab keys usable in triggers (``user``, ``posixAccount``, ...)."""
    keys: dict[str, None] = {}
    for info in registry.list():
        for tab in info.tabs:
            keys.setdefault(tab.acl_key or tab.name, None)
    return sorted(keys, key=str.lower)


# ------------------------------------------------------------ plugin details


def describe_plugins(registry: TypeRegistry) -> list[dict[str, Any]]:
    """Every discovered plugin with its version, state, missing classes and contributions."""
    contributions: dict[str, Plugin] = {}
    for point in entry_points(group=PLUGIN_GROUP):
        try:
            loaded = point.load()
            plugin = cast("Plugin", loaded() if callable(loaded) else loaded)
        except Exception as exc:  # a broken plugin is reported through the registry status
            log.warning("plugin_describe_failed", plugin=point.name, error=type(exc).__name__)
            continue
        contributions[plugin.name] = plugin
    out: list[dict[str, Any]] = []
    for status in sorted(registry.plugins, key=lambda s: s.name):
        plugin = contributions.get(status.name)
        types: list[dict[str, str]] = []
        tabs: list[dict[str, str]] = []
        if plugin is not None:
            types = [
                {"name": t.name, "label": t.label, "category": t.category} for t in plugin.types
            ]
            tabs = [
                {"type": a.type_name, "name": a.tab.name, "label": a.tab.display_label()}
                for a in plugin.tabs
            ]
        out.append(
            {
                "name": status.name,
                "version": status.version,
                "enabled": status.enabled,
                "missing_object_classes": list(status.missing_object_classes),
                "types": types,
                "tabs": tabs,
                "required_object_classes": list(plugin.required_object_classes) if plugin else [],
            }
        )
    return out


# -------------------------------------------------------------------- tasks

_FAILED = ("failed", "error", "failure")
_DONE = ("done", "completed", "finished")


def _utc_text(entry_value: str | None) -> str | None:
    if not entry_value:
        return None
    try:
        return parse_generalized_time(entry_value).astimezone(UTC).isoformat()
    except ValueError:
        return entry_value


def task_rows(
    user: CurrentUser,
    domain: Domain,
    *,
    kind: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Task objects readable by the user, with the progress of their granular sub-tasks."""
    directory = user.directory
    evaluator = domain.evaluator(user)
    granular: dict[str, list[tuple[str, str]]] = {}
    try:
        for entry in directory.search(
            directory.base_dn, f"(objectClass={schema.OC.TASKS_GRANULAR})", Scope.SUBTREE
        ):
            master = entry.text(schema.TASKS_GRANULAR_MASTER_ATTR)
            if master:
                granular.setdefault(dnlib.normalize(master), []).append(
                    (
                        entry.dn,
                        (entry.text(schema.TASKS_GRANULAR_STATUS_ATTR) or "").strip(),
                    )
                )
    except NoSuchObjectError:
        pass
    rows: list[dict[str, Any]] = []
    for info in domain.registry.list():
        if info.acl_category != "tasks" or (kind and info.name != kind):
            continue
        key = info.acl_object(info.main_tab)
        try:
            found = list(directory.search(directory.base_dn, info.type.filter, Scope.SUBTREE))
        except NoSuchObjectError:
            continue
        for entry in found:
            if not domain.is_admin(user.dn) and not evaluator.permissions(entry.dn, key).read:
                continue
            state = (entry.text(schema.TASKS_STATUS_ATTR) or "").strip()
            if status and state.lower() != status.lower():
                continue
            subs = granular.get(dnlib.normalize(entry.dn), [])
            failed = [d for d, s in subs if s.lower() in _FAILED]
            rows.append(
                {
                    "dn": entry.dn,
                    "name": entry.text("cn") or dnlib.rdn(entry.dn),
                    "kind": info.name,
                    "kind_label": info.type.label,
                    "status": state,
                    "created": _utc_text(entry.text(schema.TASKS_CREATION_DATE_ATTR)),
                    "last_run": _utc_text(entry.text(schema.TASKS_LAST_EXEC_ATTR)),
                    "next_run": _utc_text(entry.text(schema.TASKS_NEXT_EXEC_ATTR)),
                    "subtasks": {
                        "total": len(subs),
                        "done": sum(
                            1 for _d, s in subs if s.lower() in ("done", "completed", "finished")
                        ),
                        "failed": len(failed),
                    },
                    "failed_subtasks": failed,
                    "can_run": rights_of(user, domain, key, entry.dn).write,
                }
            )
    rows.sort(key=lambda r: (r["kind"], str(r["name"]).lower()))
    return rows


def _task_entry(user: CurrentUser, domain: Domain, dn: str) -> tuple[Any, str]:
    directory = user.directory
    entry = directory.get(dn)
    if entry is None or not entry.has_object_class(schema.OC.TASKS):
        raise not_found("Task not found")
    for info in domain.registry.list():
        if info.acl_category == "tasks" and dnlib.is_descendant(dn, directory.base_dn):
            key = info.acl_object(info.main_tab)
            if rights_of(user, domain, key, dn).write:
                return entry, key
    raise forbidden("You cannot run this task")


# ---------------------------------------------------------------- schemas


class RoleBody(BaseModel):
    base: str | None = None
    cn: str = ""
    description: str = ""
    templates: list[dict[str, Any]] = Field(default_factory=lambda: [])


class RolePatch(BaseModel):
    description: str | None = None
    templates: list[dict[str, Any]] | None = None


class AssignmentsBody(BaseModel):
    assignments: list[dict[str, Any]] = Field(default_factory=lambda: [])


class CheckRightsBody(BaseModel):
    user: str
    dn: str
    object: str
    attributes: list[str] = Field(default_factory=lambda: [])


class ConfigBody(BaseModel):
    changes: dict[str, Any] = Field(default_factory=lambda: {})


class HookBody(BaseModel):
    tab: str
    mode: str
    command: str
    enabled: bool = True


class HooksBody(BaseModel):
    hooks: list[HookBody] = Field(default_factory=lambda: [])
    display_output: bool | None = None


class FixBody(BaseModel):
    dns: list[str] = Field(default_factory=lambda: [])
    options: dict[str, str] = Field(default_factory=lambda: {})


# ------------------------------------------------------------------ router


def build_router(settings: TriggerSettings | None = None) -> APIRouter:
    """The ``/admin`` router (``settings`` is the plugin settings object, may be ``None``)."""
    router = APIRouter(prefix="/admin", tags=["admin"], lifespan=runtime_lifespan)
    holder = settings

    def remember(domain: Domain) -> None:
        if holder is not None:
            holder.registry = domain.registry

    # ------------------------------------------------------ capabilities

    @router.get("/capabilities")
    def capabilities(user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        remember(domain)
        evaluator = None if domain.is_admin(user.dn) else domain.evaluator(user)
        base = user.directory.base_dn

        def can(key: str) -> bool:
            return evaluator is None or evaluator.permissions(base, key).read

        has_tasks = evaluator is None or any(
            not evaluator.permissions(base, f"{info.acl_category}/0").is_empty
            for info in domain.registry.list()
            if info.acl_category == "tasks"
        )
        config = can(CONFIG_KEY)
        acl = can(ROLE_KEY) or can(ASSIGNMENT_KEY)
        return {
            "is_admin": domain.is_admin(user.dn),
            # administration console (else the self-service portal)
            "console": evaluator is None or acl or config or evaluator.manages_others(),
            "acl": acl,
            "config": config,
            "config_write": rights_of(user, domain, CONFIG_KEY).write,
            "hooks": config,
            "health": config,
            "plugins": config,
            "tasks": has_tasks,
        }

    # -------------------------------------------------------------- ACL

    @router.get("/acl/catalog")
    def acl_catalog(user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        _require(user, domain, ROLE_KEY, "r")
        return build_catalog(domain.registry)

    @router.get("/acl/roles")
    def list_roles(
        user: CurrentUserDep, domain: DomainDep, base: str | None = None
    ) -> list[dict[str, Any]]:
        _require(user, domain, ROLE_KEY, "r")
        roles = acl_admin.list_roles(user.directory, base)
        used: dict[str, int] = {}
        for entry_dn, _index in _all_role_uses(user):
            used[dnlib.normalize(entry_dn)] = used.get(dnlib.normalize(entry_dn), 0) + 1
        out: list[dict[str, Any]] = []
        for role in roles:
            if not rights_of(user, domain, ROLE_KEY, role.dn).read:
                continue
            item = role.to_json()
            item["used_by"] = used.get(dnlib.normalize(role.dn), 0)
            out.append(item)
        return out

    def _all_role_uses(user: CurrentUser) -> list[tuple[str, int]]:
        from heracles.acl.model import AclAssignment
        from heracles.acl.parser import parse_assignment

        uses: list[tuple[str, int]] = []
        for group in acl_admin.all_assignments(user.directory):
            for item in group["assignments"]:
                parsed = parse_assignment(item["raw"])
                if isinstance(parsed, AclAssignment):
                    uses.append((parsed.role_dn, parsed.index))
        return uses

    @router.get("/acl/roles/{dn:path}")
    def get_role(dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        _require(user, domain, ROLE_KEY, "r", dn)
        role = acl_admin.get_role(user.directory, dn)
        if role is None:
            raise not_found("Role not found")
        return role.to_json()

    @router.post("/acl/roles", status_code=201)
    def create_role(body: RoleBody, user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        department = body.base or user.directory.base_dn
        _require(user, domain, ROLE_KEY, "c", department)
        with admin_errors():
            container = acl_admin.role_container(user.directory, department, None)
            dn = acl_admin.create_role(
                user.directory,
                container=container,
                cn=body.cn,
                description=body.description,
                templates=body.templates,
            )
            role = acl_admin.get_role(user.directory, dn)
        assert role is not None
        _audit(user, domain, "acl", "acl_role", dn, "role created")
        return role.to_json()

    @router.put("/acl/roles/{dn:path}")
    def update_role(
        dn: str, body: RolePatch, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, Any]:
        _require(user, domain, ROLE_KEY, "w", dn)
        with admin_errors():
            role = acl_admin.update_role(
                user.directory, dn, description=body.description, templates=body.templates
            )
        invalidate_acl_cache(user.session)
        _audit(user, domain, "acl", "acl_role", dn, "role updated")
        return role.to_json()

    @router.delete("/acl/roles/{dn:path}", status_code=204)
    def delete_role(
        dn: str,
        user: CurrentUserDep,
        domain: DomainDep,
        force: bool = Query(default=False),
    ) -> Response:
        _require(user, domain, ROLE_KEY, "d", dn)
        with admin_errors():
            acl_admin.delete_role(user.directory, dn, force=force)
        invalidate_acl_cache(user.session)
        _audit(user, domain, "acl", "acl_role", dn, "role deleted")
        return Response(status_code=204)

    @router.get("/acl/assignments")
    def all_assignments(user: CurrentUserDep, domain: DomainDep) -> list[dict[str, Any]]:
        _require(user, domain, ASSIGNMENT_KEY, "r")
        return [
            g
            for g in acl_admin.all_assignments(user.directory)
            if rights_of(user, domain, ASSIGNMENT_KEY, g["dn"]).read
        ]

    @router.get("/acl/assignments/{dn:path}")
    def entry_assignments(dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        _require(user, domain, ASSIGNMENT_KEY, "r", dn)
        with admin_errors():
            return {"dn": dn, "assignments": acl_admin.list_assignments(user.directory, dn)}

    @router.put("/acl/assignments/{dn:path}")
    def put_assignments(
        dn: str, body: AssignmentsBody, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, Any]:
        _require(user, domain, ASSIGNMENT_KEY, "w", dn)
        with admin_errors():
            items = acl_admin.set_assignments(user.directory, dn, body.assignments)
        invalidate_acl_cache(user.session)
        _audit(user, domain, "acl", "acl_assignment", dn, f"assignments: {len(items)}")
        return {"dn": dn, "assignments": items}

    @router.post("/acl/check")
    def check_rights(
        body: CheckRightsBody, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, Any]:
        _require(user, domain, ASSIGNMENT_KEY, "r")
        with admin_errors():
            report = acl_admin.check_rights(
                user.directory,
                user_dn=body.user,
                target_dn=body.dn,
                object_key=body.object,
                attributes=body.attributes,
                category_tabs=domain.category_tabs(),
                target_limit=domain.acl_target_limit,
            )
        result = report.to_json()
        result["bootstrap_admin"] = domain.is_admin(body.user)
        return result

    # ----------------------------------------------------------- config

    def config_view(user: CurrentUser, domain: Domain, state: AppState) -> dict[str, Any]:
        rights = rights_of(user, domain, CONFIG_KEY)
        config = effective(state, user.directory_id)
        snapshot = config_store.read_config(user.directory)
        fields: list[dict[str, Any]] = []
        for meta in config_store.describe_fields():
            key = meta["key"]
            hidden = bool(meta["secret"]) and not rights.write
            fields.append(
                {
                    **meta,
                    "value": None if hidden else config.values.get(key),
                    "source": "directory" if key in snapshot.values else "default",
                    "hidden": hidden,
                }
            )
        return {
            "exists": snapshot.exists,
            "can_write": rights.write,
            "sections": list(config_store.SECTIONS),
            "fields": fields,
        }

    @router.get("/config")
    def get_config(user: CurrentUserDep, domain: DomainDep, state: StateDep) -> dict[str, Any]:
        remember(domain)
        _require(user, domain, CONFIG_KEY, "r")
        return config_view(user, domain, state)

    @router.put("/config")
    def put_config(
        body: ConfigBody, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, Any]:
        remember(domain)
        _require(user, domain, CONFIG_KEY, "w")
        forbidden_keys = {"tab_hooks", "display_hook_output"} & set(body.changes)
        if forbidden_keys:
            raise validation(
                "Invalid configuration",
                {k: "Use the triggers endpoint." for k in sorted(forbidden_keys)},
            )
        with admin_errors():
            config_store.save_config(user.directory, body.changes)
        apply_runtime(state, domain, user.directory_id, effective(state, user.directory_id))
        _audit(
            user,
            domain,
            "config",
            "config",
            config_store.config_dn(user.directory),
            *(f"changed: {k}" for k in sorted(body.changes)),
        )
        return config_view(user, domain, state)

    # --------------------------------------------------------- triggers

    def hooks_view(user: CurrentUser, domain: Domain, state: AppState) -> dict[str, Any]:
        config = effective(state, user.directory_id)
        hooks: list[dict[str, Any]] = []
        invalid: list[str] = []
        for raw in config.tab_hooks:
            parsed = parse_hook(raw)
            if parsed is None:
                invalid.append(raw)
            else:
                hooks.append(
                    {
                        "tab": parsed.tab,
                        "mode": parsed.mode,
                        "command": parsed.command,
                        "enabled": parsed.enabled,
                    }
                )
        return {
            "hooks": hooks,
            "invalid": invalid,
            "display_output": config.display_hook_output,
            "modes": list(HOOK_MODES),
            "tabs": tab_keys(domain.registry),
            "can_write": rights_of(user, domain, CONFIG_KEY).write,
        }

    @router.get("/hooks")
    def get_hooks(user: CurrentUserDep, domain: DomainDep, state: StateDep) -> dict[str, Any]:
        remember(domain)
        _require(user, domain, CONFIG_KEY, "r")
        return hooks_view(user, domain, state)

    @router.put("/hooks")
    def put_hooks(
        body: HooksBody, user: CurrentUserDep, domain: DomainDep, state: StateDep
    ) -> dict[str, Any]:
        remember(domain)
        _require(user, domain, CONFIG_KEY, "w")
        errors: dict[str, str] = {}
        values: list[str] = []
        for index, item in enumerate(body.hooks):
            tab = item.tab.strip()
            if not tab or any(ch in tab for ch in "|\n"):
                errors[f"hooks.{index}.tab"] = "Invalid tab."
            if item.mode not in HOOK_MODES:
                errors[f"hooks.{index}.mode"] = "Unknown mode."
            if not item.command.strip() or "\n" in item.command:
                errors[f"hooks.{index}.command"] = "A single-line command is required."
            if not any(k.startswith(f"hooks.{index}.") for k in errors):
                values.append(
                    TabHook(tab, item.mode, item.command.strip(), item.enabled).serialise()
                )
        if errors:
            raise validation("Invalid triggers", errors)
        current = effective(state, user.directory_id)
        kept = [raw for raw in current.tab_hooks if parse_hook(raw) is None]
        changes: dict[str, Any] = {"tab_hooks": [*values, *kept]}
        if body.display_output is not None:
            changes["display_hook_output"] = body.display_output
        with admin_errors():
            config_store.save_config(user.directory, changes)
        _audit(
            user,
            domain,
            "config",
            "hooks",
            config_store.config_dn(user.directory),
            f"hooks: {len(values)}",
        )
        return hooks_view(user, domain, state)

    # ----------------------------------------------------------- health

    def check_context(user: CurrentUser, domain: Domain) -> setup_checks.CheckContext:
        return setup_checks.context_for(user.directory, sorted(domain.admin_dns))

    @router.get("/checks")
    def run_checks(user: CurrentUserDep, domain: DomainDep) -> list[dict[str, Any]]:
        remember(domain)
        _require(user, domain, CONFIG_KEY, "r")
        return [r.to_json() for r in setup_checks.run_checks(check_context(user, domain))]

    @router.post("/checks/{check_id}/fix")
    def fix_check(
        check_id: str, body: FixBody, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, Any]:
        _require(user, domain, CONFIG_KEY, "w")
        ctx = check_context(user, domain)
        try:
            outcome = setup_checks.run_fix(ctx, check_id, body.dns, body.options)
        except setup_checks.UnknownCheckError:
            raise not_found("This check has no fix") from None
        invalidate_acl_cache(user.session)
        _audit(user, domain, "config", "setup_check", user.directory.base_dn, f"fix: {check_id}")
        remaining = setup_checks.run_checks(ctx, [check_id])
        return {"result": outcome.to_json(), "check": remaining[0].to_json() if remaining else None}

    # ---------------------------------------------------------- plugins

    @router.get("/plugins")
    def plugins(user: CurrentUserDep, domain: DomainDep) -> list[dict[str, Any]]:
        remember(domain)
        _require(user, domain, CONFIG_KEY, "r")
        return describe_plugins(domain.registry)

    # ------------------------------------------------------------ tasks

    @router.get("/tasks")
    def tasks(
        user: CurrentUserDep,
        domain: DomainDep,
        kind: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        rows = task_rows(user, domain, kind=kind, status=status)
        kinds = sorted(
            {(i.name, i.type.label) for i in domain.registry.list() if i.acl_category == "tasks"}
        )
        return {
            "tasks": rows,
            "kinds": [{"name": n, "label": label} for n, label in kinds],
            "summary": {
                "total": len(rows),
                "active": sum(1 for r in rows if r["status"].lower() == "activated"),
                "failed_subtasks": sum(r["subtasks"]["failed"] for r in rows),
            },
        }

    @router.post("/tasks/{dn:path}/run")
    def run_task(dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        """Ask the scheduler to run the task at its next pass (status active, due now)."""
        entry, _key = _task_entry(user, domain, dn)
        now = format_generalized_time(datetime.now(UTC)).encode()
        mods = [Modification("replace", schema.TASKS_NEXT_EXEC_ATTR, [now])]
        if (entry.text(schema.TASKS_STATUS_ATTR) or "").lower() != "activated":
            mods.append(Modification("replace", schema.TASKS_STATUS_ATTR, [b"Activated"]))
        user.directory.modify(entry.dn, mods)
        _audit(user, domain, "task", "task", entry.dn, "run requested")
        return {"dn": entry.dn, "queued": True}

    @router.post("/tasks/{dn:path}/retry")
    def retry_task(dn: str, user: CurrentUserDep, domain: DomainDep) -> dict[str, Any]:
        """Put the failed granular sub-tasks of a task back in the queue."""
        entry, _key = _task_entry(user, domain, dn)
        now = format_generalized_time(datetime.now(UTC)).encode()
        retried: list[str] = []
        for sub in user.directory.search(
            entry.dn,
            f"(&(objectClass={schema.OC.TASKS_GRANULAR})"
            f"({schema.TASKS_GRANULAR_MASTER_ATTR}={_escape(entry.dn)}))",
            Scope.SUBTREE,
        ):
            if (sub.text(schema.TASKS_GRANULAR_STATUS_ATTR) or "").lower() in _FAILED:
                user.directory.modify(
                    sub.dn,
                    [
                        Modification("replace", schema.TASKS_GRANULAR_STATUS_ATTR, [b"Activated"]),
                        Modification("replace", schema.TASKS_GRANULAR_NEXT_EXEC_ATTR, [now]),
                    ],
                )
                retried.append(sub.dn)
        _audit(user, domain, "task", "task", entry.dn, f"retried sub-tasks: {len(retried)}")
        return {"dn": entry.dn, "retried": retried}

    return router


def _escape(value: str) -> str:
    from heracles.ldap.filter import escape_filter_value

    return escape_filter_value(value)


__all__ = [
    "NO_RIGHTS",
    "apply_runtime",
    "build_catalog",
    "build_router",
    "describe_plugins",
    "task_rows",
]
