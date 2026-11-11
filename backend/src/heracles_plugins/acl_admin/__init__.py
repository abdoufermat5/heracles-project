"""Administration plugin: ACL roles, ACL assignments tab, triggers and the admin API.

* the ``acl_role`` type (role entries below ``ou=aclroles``, ACL key ``acl/aclRole``);
* the ``acl`` tab attached to the department types (editing the assignments stored on the
  department; ACL key ``<department category>/aclAssignment``);
* :class:`heracles.triggers.TriggerEvents` registered as object event hook;
* the ``/api/v2/admin`` router.
"""

from __future__ import annotations

from typing import Any

from heracles.acl.model import AclAssignment, AclScope, Ignored
from heracles.acl.parser import parse_assignment, parse_role_value, serialise_assignment
from heracles.attributes import (
    CompositeAttr,
    DepartmentAttr,
    HiddenAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.i18n import _
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles.objects.registry import EventsContext, PluginRouterContext
from heracles.schema.names import ATTR, OC
from heracles.triggers import TriggerEvents, TriggerSettings

PLUGIN_NAME = "acl_admin"
NAME_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"
DEPARTMENT_TYPES = ("department", "department_o", "department_l", "department_c", "department_dc")


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


# ------------------------------------------------------------------ ACL role


class AclRole(ObjectType):
    """A set of rights that can be assigned to users, groups and roles."""

    name = "acl_role"
    acl_category = "acl"
    label = _("Access role")
    label_plural = _("Access roles")
    icon = "key"
    category = "access"
    filter = f"(objectClass={OC.ACL_ROLE})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=aclroles"
    columns = ("cn", "description")
    search_attrs = ("cn", "description")

    class Main(Tab):
        name = "main"
        acl_key = "aclRole"
        label = _("Role")
        object_classes = (OC.ACL_ROLE,)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            TextAttr("description", _("Description")),
        )
        rights = Section(
            _("Rights"),
            ListAttr(
                ATTR.ACL_TEMPLATE,
                _("Rights templates"),
                StringAttr("template", _("Template")),
                required=True,
                description=_(
                    "One value per line: <index>:<object>;<rights>#<attribute>;<rights>,... "
                    "Use the access control section for the structured editor."
                ),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            for index, value in enumerate(ctx.values.get(ATTR.ACL_TEMPLATE) or []):
                if isinstance(parse_role_value(str(value)), Ignored):
                    ctx.error(
                        ATTR.ACL_TEMPLATE,
                        _("Invalid rights template (line {n}).").format(n=index + 1),
                    )
                    return


# ---------------------------------------------------------- assignments tab


def _assignment_item() -> CompositeAttr:
    return CompositeAttr(
        "assignment",
        _("Assignment"),
        [
            IntAttr("index", _("Priority"), min=0),
            SelectAttr(
                "scope",
                _("Scope"),
                options=[
                    ("subtree", _("This department and everything below")),
                    ("base", _("This department only")),
                ],
                required=True,
            ),
            ObjectRefAttr("role", _("Role"), ref_type="acl_role", required=True),
            ListAttr(
                "members",
                _("Members"),
                StringAttr("member", _("Member")),
                required=True,
                description=_("DNs of users, groups or roles; * stands for every user."),
            ),
            StringAttr("user_filter", _("User filter")),
            StringAttr("target_filter", _("Target filter")),
        ],
    )


class AclAssignmentsTab(Tab):
    """Assignments of ACL roles stored on a department."""

    name = "acl"
    acl_key = "aclAssignment"
    label = _("Access control")
    optional = True
    object_classes = (OC.ACL_ASSIGNMENT,)

    assignments = Section(
        _("Assignments"),
        virtual(
            ListAttr(
                "assignments",
                _("Assignments"),
                _assignment_item(),
                description=_("Who gets which role on this department."),
            )
        ),
        ListAttr(
            ATTR.ACL_ENTRY,
            _("Stored values"),
            HiddenAttr(ATTR.ACL_ENTRY, _("Value")),
            readonly=True,
            description=_("Technical form of the assignments (read-only)."),
        ),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        items: list[dict[str, Any]] = []
        stored: list[str] = ctx.values.get(ATTR.ACL_ENTRY) or []
        for raw in stored:
            parsed = parse_assignment(str(raw))
            if isinstance(parsed, Ignored):
                continue
            items.append(
                {
                    "index": parsed.index,
                    "scope": parsed.scope.value,
                    "role": parsed.role_dn,
                    "members": list(parsed.members),
                    "user_filter": parsed.user_filter,
                    "target_filter": parsed.target_filter,
                }
            )
        items.sort(key=lambda i: i["index"])
        ctx.values["assignments"] = items or None

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        if not ctx.was_touched("assignments") and not ctx.activating:
            return
        values: list[str] = []
        for position, item in enumerate(ctx.values.get("assignments") or []):
            member_values: list[Any] = item.get("members") or []
            members = [str(m) for m in member_values if str(m).strip()]
            if not members or not item.get("role"):
                ctx.error(
                    "assignments",
                    _("Assignment {n} needs a role and members.").format(n=position + 1),
                )
                return
            try:
                scope = AclScope(str(item.get("scope") or "subtree"))
            except ValueError:
                ctx.error("assignments", _("Unknown scope."))
                return
            values.append(
                serialise_assignment(
                    AclAssignment(
                        int(item.get("index") or position),
                        scope,
                        str(item["role"]),
                        tuple(members),
                        str(item.get("user_filter") or "").strip() or None,
                        str(item.get("target_filter") or "").strip() or None,
                    )
                )
            )
        # values that cannot be parsed are kept as they are
        previous: list[str] = ctx.original_values().get(ATTR.ACL_ENTRY) or []
        values.extend(raw for raw in previous if isinstance(parse_assignment(raw), Ignored))
        if not values:
            ctx.error("assignments", _("At least one assignment is required."))
            return
        ctx.values[ATTR.ACL_ENTRY] = values


# --------------------------------------------------------------------- plugin


def _trigger_events(ctx: EventsContext) -> TriggerEvents:
    settings = ctx.settings if isinstance(ctx.settings, TriggerSettings) else TriggerSettings()
    return TriggerEvents(ctx.directory, ctx.user_dn, settings)


def _admin_router(ctx: PluginRouterContext) -> Any:
    from heracles.api.v2 import admin

    return admin.build_router(ctx.settings if isinstance(ctx.settings, TriggerSettings) else None)


def plugin() -> Plugin:
    """Entry point of the administration plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(AclRole,),
        tabs=tuple(TabAttachment(name, AclAssignmentsTab) for name in DEPARTMENT_TYPES),
        required_object_classes=(OC.ACL_ROLE, OC.ACL_ASSIGNMENT),
        settings=TriggerSettings(),
        object_events=(_trigger_events,),
        api_routers=(_admin_router,),
    )


__all__ = ["AclAssignmentsTab", "AclRole", "plugin"]
