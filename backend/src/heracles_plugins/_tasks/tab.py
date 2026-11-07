"""Base tab and base type of a task kind (``fdTasks`` entries below ``ou=tasks``)."""

from __future__ import annotations

from datetime import UTC, datetime

from heracles.attributes import (
    BooleanAttr,
    DateTimeAttr,
    DepartmentAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins._tasks.helpers import STATUS_ACTIVATED, STATUS_DEACTIVATED
from heracles_plugins._tasks.runner import TASKS_RDN

NAME_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"


class TaskObjectType(ObjectType):
    """Base of the task kinds: set ``name``, ``label``, ``filter`` and a nested ``Main`` tab."""

    acl_category = "tasks"
    icon = "clock"
    category = "workflow"
    main_attr = "cn"
    name_attr = "cn"
    rdn = TASKS_RDN
    columns = ("cn", "fdTasksStatus", "fdTasksNextExec")
    search_attrs = ("cn", "description")


class TaskTab(Tab):
    """Properties and schedule sections common to every task kind.

    Subclass it, set ``name``, ``acl_key`` and ``object_classes`` (``fdTasks`` plus the
    kind's auxiliary class) and add the sections of the kind; override ``prepare`` and
    call ``super().prepare(ctx)`` to add checks.
    """

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

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        values = ctx.values
        if not values.get("fdTasksStatus"):
            values["fdTasksStatus"] = STATUS_ACTIVATED
        if values.get("fdTasksRepeatable") and not values.get("fdTasksRepeatableSchedule"):
            ctx.error("fdTasksRepeatableSchedule", _("Required for a repeatable task."))
        if ctx.creating:
            ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))
            values["fdTasksCreationDate"] = datetime.now(UTC).replace(microsecond=0)
            if not values.get("fdTasksNextExec") and values.get("fdTasksScheduleDate"):
                values["fdTasksNextExec"] = values["fdTasksScheduleDate"]
