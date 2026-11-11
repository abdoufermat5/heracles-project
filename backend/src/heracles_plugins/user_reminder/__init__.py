"""User reminder plugin: mail users before their account expires.

Provides the ``reminder_task`` and ``mail_template`` object types, the pure
runner :func:`run_reminders` and the unauthenticated prolongation endpoint.

Integration notes for the framework owners:

* CLI / scheduler: build a ``DirectoryClient`` and a ``Mailer`` and call
  ``run_reminders(directory, mailer, datetime.now(UTC), base_url,
  registry.settings["user_reminder"])``; the returned ``RunReport`` lists what
  was sent. Run it periodically (hourly is enough; each task keeps its own
  next execution date).
* Prolongation endpoint: ``build_prolong_router(get_directory, settings)`` returns
  a router serving ``POST /api/v2/reminder/prolong``. It must be included on
  the application itself (``app.include_router``), not in the session and CSRF
  protected ``/api/v2`` router, because the caller is not logged in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from heracles.attributes import (
    BooleanAttr,
    DepartmentAttr,
    EmailAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles.objects.registry import PluginRouterContext
from heracles_plugins._tasks import NAME_RE, TaskObjectType, TaskTab
from heracles_plugins.user_reminder.prolong import (
    ProlongError,
    build_prolong_router,
    prolong_account,
)

if TYPE_CHECKING:
    from fastapi import APIRouter

from heracles_plugins.user_reminder.runner import (
    SCHEDULES,
    TASK_FILTER,
    TEMPLATE_FIELDS,
    ReminderRecord,
    RunReport,
    create_prolongation_token,
    expand_members,
    next_execution,
    render_template,
    run_reminders,
)

PLUGIN_NAME = "user_reminder"


@dataclass(slots=True)
class UserReminderSettings:
    """Settings of the user reminder plugin."""

    #: Days added to ``shadowExpire`` when a user follows the prolongation link.
    prolongation_days: int = 30


class ReminderTask(TaskObjectType):
    """A task reminding users that their account is about to expire."""

    name = "reminder_task"
    label = _("Reminder task")
    label_plural = _("Reminder tasks")
    nav = "hidden"
    icon = "bell"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "reminderTask"
        label = _("Reminder")
        object_classes = ("hrcTasks", "hrcTasksReminder")

        reminder = Section(
            _("Reminder"),
            IntAttr(
                "hrcTasksReminderFirstCall",
                _("First reminder (days before expiration)"),
                required=True,
                min=0,
            ),
            IntAttr(
                "hrcTasksReminderSecondCall",
                _("Second reminder (days before expiration)"),
                min=0,
            ),
            BooleanAttr(
                "hrcTasksReminderPosix",
                _("Monitor the Unix account expiration date"),
                description=_("Always enabled"),
                default=True,
                readonly=True,
            ),
            BooleanAttr(
                "hrcTasksReminderAccountProlongation",
                _("Include an account prolongation link"),
                default=False,
            ),
            ObjectRefAttr(
                "hrcTasksReminderMailTemplate",
                _("Mail template"),
                ref_type="mail_template",
                required=True,
                description=_(
                    "Placeholders: {uid} {cn} {givenName} {sn} {mail} "
                    "{expiration_date} {days_left} {prolongation_url}"
                ),
            ),
            EmailAttr("hrcTasksReminderEmailSender", _("Sender address"), required=True),
        )
        members = Section(
            _("Recipients"),
            ListAttr(
                "hrcTasksReminderMembers",
                _("Monitored users, groups or roles"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
            ListAttr(
                "hrcTasksReminderRecipientsMembers",
                _("Copy recipients"),
                ObjectRefAttr("recipient", _("Recipient"), ref_type="user"),
                description=_("Users, groups or roles receiving a copy of every reminder"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            ctx.values["hrcTasksReminderPosix"] = True
            super().prepare(ctx)


class MailTemplate(ObjectType):
    """A mail subject and body with ``{placeholders}``."""

    name = "mail_template"
    acl_category = "mailTemplate"
    label = _("Mail template")
    label_plural = _("Mail templates")
    icon = "file"
    category = "mail"
    filter = "(objectClass=hrcMailTemplate)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=mailTemplate"
    columns = ("cn", "hrcMailTemplateSubject")
    search_attrs = ("cn", "hrcMailTemplateSubject")

    class Main(Tab):
        name = "main"
        acl_key = "mailTemplate"
        label = _("Mail template")
        object_classes = ("hrcMailTemplate",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            StringAttr("hrcMailTemplateSubject", _("Subject"), required=True),
            TextAttr(
                "hrcMailTemplateBody",
                _("Body"),
                required=True,
                description=_(
                    "Placeholders: {uid} {cn} {givenName} {sn} {mail} "
                    "{expiration_date} {days_left} {prolongation_url}"
                ),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(MailTemplate.rdn, ctx.base))


def plugin() -> Plugin:
    """Entry point of the user reminder plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(ReminderTask, MailTemplate),
        required_object_classes=("hrcTasks", "hrcTasksReminder"),
        settings=UserReminderSettings(),
        public_routers=(_prolong_router,),
    )


def _prolong_router(ctx: PluginRouterContext) -> APIRouter:
    """Public ``POST /api/v2/reminder/prolong`` on the first configured directory."""
    directory = next(iter(ctx.directories.values()))
    settings = ctx.settings if ctx.settings is not None else UserReminderSettings()
    return build_prolong_router(lambda: directory, settings)


__all__ = [
    "SCHEDULES",
    "TEMPLATE_FIELDS",
    "MailTemplate",
    "ProlongError",
    "ReminderRecord",
    "ReminderTask",
    "RunReport",
    "UserReminderSettings",
    "build_prolong_router",
    "create_prolongation_token",
    "expand_members",
    "next_execution",
    "plugin",
    "prolong_account",
    "render_template",
    "run_reminders",
]
