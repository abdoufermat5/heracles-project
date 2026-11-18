"""Automatic groups plugin: keep group memberships in line with a rule.

Provides the ``automatic_groups_task`` type (``hrcTasks`` + ``hrcTasksAutomaticGroups``, ACL
``tasks/automaticGroupsTask``) and the pure runner :func:`run_automatic_groups`.

A task looks at its users (users, or groups and roles expanded to users), keeps those whose
attribute matches a regular expression (``[attribute:]regex``, the attribute defaults to
the login) and adds them to the chosen group. For a dynamic group, users of the task that no
longer match are removed too. The group may be a ``groupOfNames`` or a POSIX group.

"""

from __future__ import annotations

from heracles.api.domain import TypeAclPolicy
from heracles.attributes import BooleanAttr, ListAttr, ObjectRefAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import Entry
from heracles.objects import Plugin, Section
from heracles.objects.errors import UnknownTypeError
from heracles.objects.hooks import TabContext
from heracles.objects.registry import TypeRegistry
from heracles.objects.task_runner import TaskRunContext, TaskRunner
from heracles_plugins._patterns import PatternError
from heracles_plugins._tasks import TaskObjectType, TaskTab
from heracles_plugins._tasks.author import AuthorRights, author_section, stamp_author
from heracles_plugins.automatic_groups.runner import (
    TASK_CLASS,
    TASK_FILTER,
    AutomaticGroupsReport,
    AutomaticGroupsSettings,
    ForbiddenAttributeError,
    GroupAuthorizer,
    MembershipChange,
    group_target,
    parse_rule,
    run_automatic_groups,
)

PLUGIN_NAME = "automatic_groups"


class AutomaticGroupsTask(TaskObjectType):
    """A task adding and removing users in a group."""

    name = "automatic_groups_task"
    label = _("Automatic groups task")
    label_plural = _("Automatic groups tasks")
    nav = "hidden"
    icon = "users"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "automaticGroupsTask"
        label = _("Automatic groups")
        object_classes = ("hrcTasks", TASK_CLASS)

        rule = Section(
            _("Rule"),
            ObjectRefAttr(
                "hrcTasksAutomaticGroupsOfName",
                _("Group"),
                ref_type="group",
                required=True,
                description=_("Group that receives the matching users"),
            ),
            StringAttr(
                "hrcTasksAutomaticGroupsRegexPattern",
                _("Pattern"),
                description=_(
                    "Regular expression, optionally prefixed by an attribute name and a colon, "
                    "for example mail:@example\\.com$ (default attribute: login)"
                ),
            ),
            BooleanAttr(
                "hrcTasksAutomaticGroupsDynamicGroup",
                _("Dynamic group"),
                description=_("Also remove the users that no longer match"),
                default=False,
            ),
        )
        author = author_section()
        members = Section(
            _("Users"),
            ListAttr(
                "hrcTasksAutomaticGroupsMembers",
                _("Users, groups or roles"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            _check_author(ctx)
            pattern = ctx.values.get("hrcTasksAutomaticGroupsRegexPattern")
            if isinstance(pattern, str) and pattern:
                try:
                    parse_rule(pattern, "uid")
                except PatternError as exc:
                    ctx.error("hrcTasksAutomaticGroupsRegexPattern", str(exc))
                except ForbiddenAttributeError as exc:
                    ctx.error(
                        "hrcTasksAutomaticGroupsRegexPattern",
                        _("The rule cannot test the attribute {name}.").format(name=exc),
                    )


def _check_author(ctx: TabContext) -> None:
    """The task runs with the server's rights: its author must be allowed to do its work."""
    author = getattr(ctx.policy, "user_dn", None)
    if not isinstance(author, str):
        return  # an internal save, no acting user
    stamp_author(ctx)
    group_dn = ctx.values.get("hrcTasksAutomaticGroupsOfName")
    group = ctx.directory.get(group_dn) if isinstance(group_dn, str) and group_dn else None
    if group is None:
        return
    type_name, attr = group_target(group)
    if not ctx.can_write_object(type_name, group.dn, "main", attr):
        ctx.error(
            "hrcTasksAutomaticGroupsOfName",
            _("You cannot change the members of {dn}.").format(dn=group.dn),
        )


def _authorizer(ctx: TaskRunContext) -> GroupAuthorizer:
    """Whether an author may change a group, from the author's ACLs (resolved once per run)."""
    registry: TypeRegistry = ctx.registry
    rights = AuthorRights(ctx.directory, registry, ctx.admin_dns)

    def authorize(author: str, group: Entry) -> bool:
        acl = rights.evaluator_for(author)
        if acl is None:
            return False
        type_name, attr = group_target(group)
        try:
            policy = TypeAclPolicy(acl, registry.get(type_name), registry)
        except UnknownTypeError:
            return False
        return policy.can_write(group.dn, "main", attr)

    return authorize


def plugin() -> Plugin:
    """Entry point of the automatic groups plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(AutomaticGroupsTask,),
        required_object_classes=("hrcTasks", TASK_CLASS),
        settings=AutomaticGroupsSettings(),
        task_runners=(TaskRunner(PLUGIN_NAME, _run, kind=AutomaticGroupsTask.name),),
    )


def _run(ctx: TaskRunContext) -> AutomaticGroupsReport:
    settings = ctx.settings if isinstance(ctx.settings, AutomaticGroupsSettings) else None
    return run_automatic_groups(ctx.directory, ctx.now, settings, _authorizer(ctx))


__all__ = [
    "AutomaticGroupsReport",
    "AutomaticGroupsSettings",
    "AutomaticGroupsTask",
    "MembershipChange",
    "parse_rule",
    "plugin",
    "run_automatic_groups",
]
