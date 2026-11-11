"""SOGo plugin: calendar resources (rooms and equipment)."""

from __future__ import annotations

from dataclasses import dataclass

from heracles.attributes import (
    DepartmentAttr,
    EmailAttr,
    HiddenAttr,
    IntAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "sogo"

RESOURCE_KINDS: tuple[tuple[str, str], ...] = (
    ("location", _("Location / Room")),
    ("thing", _("Equipment / Thing")),
    ("group", _("Group")),
)


@dataclass(slots=True)
class SogoSettings:
    """Settings of the SOGo plugin."""

    rdn: str = "ou=resources"


def settings_of(ctx: TabContext) -> SogoSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, SogoSettings) else SogoSettings()


class SogoResourceTab(Tab):
    """Main tab of a SOGo calendar resource."""

    name = "main"
    acl_key = "sogoResource"
    label = _("Resource")
    object_classes = ("inetOrgPerson", "hrcCalendarResource")

    identity = Section(
        _("Identity"),
        DepartmentAttr("base", _("Department")),
        StringAttr(
            "uid",
            _("Resource name"),
            required=True,
            description=_("Identifier / name of the calendar resource (e.g. room-101)"),
        ),
        EmailAttr(
            "mail",
            _("Email"),
            description=_("Email address for calendar invitations"),
        ),
        TextAttr(
            "description",
            _("Description"),
            description=_("Resource description (equipment details, capacity, location)"),
        ),
        HiddenAttr("cn", "cn"),
        HiddenAttr("sn", "sn"),
    )
    booking = Section(
        _("Booking settings"),
        SelectAttr(
            "hrcResourceKind",
            _("Kind"),
            options=RESOURCE_KINDS,
            default="location",
            description=_("Type of resource (room, equipment, etc.)"),
        ),
        IntAttr(
            "hrcResourceMultipleBookings",
            _("Multiple bookings"),
            min=0,
            default=0,
            description=_("Maximum concurrent bookings allowed (0 for single booking)"),
        ),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        uid = ctx.values.get("uid")
        if uid and isinstance(uid, str):
            if not ctx.values.get("cn"):
                ctx.values["cn"] = uid
            if not ctx.values.get("sn"):
                ctx.values["sn"] = uid
        if ctx.creating and not ctx.errors:
            ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))


class SogoResource(ObjectType):
    """Calendar resource (room, projector, equipment) for SOGo / CalDAV."""

    name = "sogo_resource"
    acl_category = "sogo"
    label = _("Calendar resource")
    label_plural = _("Calendar resources")
    icon = "calendar"
    category = "mail"
    filter = "(objectClass=hrcCalendarResource)"
    main_attr = "uid"
    name_attr = "uid"
    rdn = "ou=resources"
    columns = ("uid", "mail", "hrcResourceKind", "description")
    search_attrs = ("uid", "mail", "description", "hrcResourceKind")
    required_object_classes = ("inetOrgPerson",)

    Main = SogoResourceTab


def plugin() -> Plugin:
    """Entry point of the SOGo plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(SogoResource,),
        settings=SogoSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "RESOURCE_KINDS",
    "SogoResource",
    "SogoResourceTab",
    "SogoSettings",
    "plugin",
    "settings_of",
]
