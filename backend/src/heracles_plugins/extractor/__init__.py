"""Extractor plugin: export attributes of users as CSV.

Provides the ``extractor_task`` type (``hrcTasks`` + ``hrcExtractorTasks``, ACL
``tasks/extractorTask``) and the pure runner :func:`run_extractor`.

A task exports chosen attributes of its members (users, or groups and roles expanded to
users) as CSV or TSV, to ``ExtractorSettings.export_directory`` (one file per run) and/or by
mail (the CSV is the mail body) to its recipients. Cells starting with a formula character
are prefixed with a quote, and password attributes can never be exported.

Integration notes: from the CLI / scheduler call ``run_extractor(directory, mailer,
datetime.now(UTC), registry.settings["extractor"])``.
"""

from __future__ import annotations

from heracles.attributes import EmailAttr, ListAttr, MultiSelectAttr, ObjectRefAttr, SelectAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section
from heracles_plugins._tasks import TaskObjectType, TaskTab
from heracles_plugins.extractor.runner import (
    FORBIDDEN_ATTRIBUTES,
    TASK_CLASS,
    TASK_FILTER,
    ExtractionRecord,
    ExtractorReport,
    ExtractorSettings,
    render_csv,
    run_extractor,
)

PLUGIN_NAME = "extractor"


class ExtractorTask(TaskObjectType):
    """A task exporting attributes of users."""

    name = "extractor_task"
    label = _("Extractor task")
    label_plural = _("Extractor tasks")
    icon = "download"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "extractorTask"
        label = _("Extractor")
        object_classes = ("hrcTasks", TASK_CLASS)

        extraction = Section(
            _("Extraction"),
            MultiSelectAttr(
                "hrcExtractorTaskAttributes",
                _("Exported attributes"),
                options=[
                    (a, a)
                    for a in ExtractorSettings().attributes
                    if a.lower() not in FORBIDDEN_ATTRIBUTES
                ],
                required=True,
            ),
            SelectAttr(
                "hrcExtractorTaskFormat",
                _("Format"),
                options=[("csv", _("CSV (comma)")), ("tsv", _("TSV (tab)"))],
                default="csv",
            ),
            ListAttr(
                "hrcExtractorTaskMembers",
                _("Exported users, groups or roles"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
        )
        delivery = Section(
            _("Delivery"),
            ListAttr(
                "hrcExtractorRecipientsMembers",
                _("Mail recipients"),
                ObjectRefAttr("recipient", _("Recipient"), ref_type="user"),
                description=_("Users, groups or roles receiving the export by mail"),
            ),
            EmailAttr("hrcExtractorEmailSender", _("Sender address")),
        )


def plugin() -> Plugin:
    """Entry point of the extractor plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(ExtractorTask,),
        required_object_classes=("hrcTasks", TASK_CLASS),
        settings=ExtractorSettings(),
    )


__all__ = [
    "ExtractionRecord",
    "ExtractorReport",
    "ExtractorSettings",
    "ExtractorTask",
    "plugin",
    "render_csv",
    "run_extractor",
]
