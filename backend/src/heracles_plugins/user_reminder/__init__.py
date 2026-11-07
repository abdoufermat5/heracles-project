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
from datetime import UTC, datetime

from heracles.attributes import (
    BooleanAttr,
    DateTimeAttr,
    DepartmentAttr,
    EmailAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins.user_reminder.prolong import (
    ProlongError,
    build_prolong_router,
    prolong_account,
)
from heracles_plugins.user_reminder.runner import (
    SCHEDULES,
    STATUS_ACTIVATED,
    STATUS_DEACTIVATED,
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
NAME_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"


@dataclass(slots=True)
class UserReminderSettings:
    """Settings of the user reminder plugin."""

    #: Days added to ``shadowExpire`` when a user follows the prolongation link.
    prolongation_days: int = 30


class ReminderTask(ObjectType):
    """A task reminding users that their account is about to expire."""

    name = "reminder_task"
    acl_category = "tasks"
    label = _("Reminder task")
    label_plural = _("Reminder tasks")
    icon = "bell"
    category = "workflow"
    filter = "(&(objectClass=fdTasks)(objectClass=fdTasksReminder))"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=tasks"
    columns = ("cn", "fdTasksStatus", "fdTasksNextExec")
    search_attrs = ("cn", "description")

    class Main(Tab):
        name = "main"
        acl_key = "reminderTask"
        label = _("Reminder")
        object_classes = ("fdTasks", "fdTasksReminder")

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            TextAttr("description", _("Description")),
            SelectAttr(
                "fdTasksStatus",
                _("Status"),
                options=[
                    (STATUS_ACTIVATED, _("Activated")),
                    (STATUS_DEACTIVATED, _("Deactivated")),
                ],
                default=STATUS_ACTIVATED,
            ),
        )
        schedule = Section(
            _("Schedule"),
            DateTimeAttr("fdTasksCreationDate", _("Creation date"), readonly=True),
            DateTimeAttr(
                "fdTasksScheduleDate",
                _("Scheduled date"),
                description=_("First execution; leave empty to run at the next scheduler pass"),
            ),
            DateTimeAttr("fdTasksLastExec", _("Last execution"), readonly=True),
            DateTimeAttr("fdTasksNextExec", _("Next execution")),
            BooleanAttr("fdTasksRepeatable", _("Repeatable"), default=False),
            SelectAttr(
                "fdTasksRepeatableSchedule",
                _("Repeat"),
                options=[
                    ("hourly", _("Hourly")),
                    ("daily", _("Daily")),
                    ("weekly", _("Weekly")),
                    ("monthly", _("Monthly")),
                    ("yearly", _("Yearly")),
                ],
            ),
        )
        reminder = Section(
            _("Reminder"),
            IntAttr(
                "fdTasksReminderFirstCall",
                _("First reminder (days before expiration)"),
                required=True,
                min=0,
            ),
            IntAttr(
                "fdTasksReminderSecondCall",
                _("Second reminder (days before expiration)"),
                min=0,
            ),
            BooleanAttr(
                "fdTasksReminderPosix",
                _("Monitor the Unix account expiration date"),
                description=_("Always enabled"),
                default=True,
                readonly=True,
            ),
            BooleanAttr(
                "fdTasksReminderAccountProlongation",
                _("Include an account prolongation link"),
                default=False,
            ),
            ObjectRefAttr(
                "fdTasksReminderMailTemplate",
                _("Mail template"),
                ref_type="mail_template",
                required=True,
                description=_(
                    "Placeholders: {uid} {cn} {givenName} {sn} {mail} "
                    "{expiration_date} {days_left} {prolongation_url}"
                ),
            ),
            EmailAttr("fdTasksReminderEmailSender", _("Sender address"), required=True),
        )
        members = Section(
            _("Recipients"),
            ListAttr(
                "fdTasksReminderMembers",
                _("Monitored users, groups or roles"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
            ListAttr(
                "fdTasksReminderRecipientsMembers",
                _("Copy recipients"),
                ObjectRefAttr("recipient", _("Recipient"), ref_type="user"),
                description=_("Users, groups or roles receiving a copy of every reminder"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            values = ctx.values
            values["fdTasksReminderPosix"] = True
            if not values.get("fdTasksStatus"):
                values["fdTasksStatus"] = STATUS_ACTIVATED
            if values.get("fdTasksRepeatable") and not values.get("fdTasksRepeatableSchedule"):
                ctx.error("fdTasksRepeatableSchedule", _("Required for a repeatable task."))
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(ReminderTask.rdn, ctx.base))
                values["fdTasksCreationDate"] = datetime.now(UTC).replace(microsecond=0)
                if not values.get("fdTasksNextExec") and values.get("fdTasksScheduleDate"):
                    values["fdTasksNextExec"] = values["fdTasksScheduleDate"]


class MailTemplate(ObjectType):
    """A mail subject and body with ``{placeholders}``."""

    name = "mail_template"
    acl_category = "mailTemplate"
    label = _("Mail template")
    label_plural = _("Mail templates")
    icon = "mail"
    category = "mail"
    filter = "(objectClass=fdMailTemplate)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=mailTemplate"
    columns = ("cn", "fdMailTemplateSubject")
    search_attrs = ("cn", "fdMailTemplateSubject")

    class Main(Tab):
        name = "main"
        acl_key = "mailTemplate"
        label = _("Mail template")
        object_classes = ("fdMailTemplate",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            StringAttr("fdMailTemplateSubject", _("Subject"), required=True),
            TextAttr(
                "fdMailTemplateBody",
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
        required_object_classes=("fdTasks", "fdTasksReminder"),
        settings=UserReminderSettings(),
    )


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
