"""Applications plugin: portal applications and the roles allowed to use them.

* ``application`` (``hrcDesktopApplication``) and ``web_application``
  (``hrcWebApplication``) live in ``ou=apps``.
* The ``applications`` tab on ``role`` lists the applications allowed for the
  role (ACL key ``role/applicationRights``).
* ``GET /api/v2/me/applications`` returns the applications granted to the
  connected user through the roles they occupy (for a portal page).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from heracles.attributes import (
    JSON,
    BooleanAttr,
    DepartmentAttr,
    HiddenAttr,
    ImageAttr,
    ListAttr,
    ObjectRefAttr,
    StringAttr,
    TextAttr,
    UrlAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.applications.router import (
    DESKTOP_CLASS,
    FLAG_LETTERS,
    FLAGS_ATTR,
    RIGHTS_CLASS,
    WEB_CLASS,
    allowed_applications,
    build_router,
    decode_flags,
    encode_flags,
)

PLUGIN_NAME = "applications"
NAME_RE = r"[A-Za-z0-9_][A-Za-z0-9_. -]*"


@dataclass(slots=True)
class ApplicationsSettings:
    """Settings of the applications plugin.

    The RDNs document the default containers; they are the ``ObjectType.rdn`` of
    the types today (the framework does not make type containers configurable).
    """

    applications_rdn: str = "ou=apps"
    webapps_rdn: str = "ou=apps"


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


# ------------------------------------------------------------------- types


class Application(ObjectType):
    """A desktop application (command to run, menu and launcher flags)."""

    name = "application"
    acl_category = "application"
    label = _("Application")
    label_plural = _("Applications")
    nav = "secondary"
    nav_group = "settings"
    icon = "app-window"
    category = "configuration"
    filter = f"(objectClass={DESKTOP_CLASS})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=apps"
    columns = ("cn", "hrcApplicationTitle", "description")
    search_attrs = ("cn", "hrcApplicationTitle", "description")

    class Main(Tab):
        name = "main"
        acl_key = "application"
        label = _("Application")
        object_classes = (DESKTOP_CLASS,)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            StringAttr("hrcApplicationTitle", _("Title"), description=_("Name shown to users")),
            TextAttr("description", _("Description")),
            StringAttr(
                "hrcApplicationExecutePath",
                _("Command"),
                description=_("Command line that starts the application"),
            ),
            ImageAttr("hrcApplicationImage", _("Icon"), max_size=(128, 128)),
        )
        flags = Section(
            _("Options"),
            virtual(BooleanAttr("flag_group", _("Run in a group session"), default=False)),
            virtual(BooleanAttr("flag_overwrite", _("Overwrite user settings"), default=False)),
            virtual(BooleanAttr("flag_desktop", _("Show on the desktop"), default=False)),
            virtual(BooleanAttr("flag_menu", _("Show in the menu"), default=False)),
            virtual(BooleanAttr("flag_launchbar", _("Show in the launch bar"), default=False)),
            HiddenAttr(FLAGS_ATTR, FLAGS_ATTR),
        )

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            raw = ctx.values.get(FLAGS_ATTR)
            ctx.values.update(decode_flags(raw if isinstance(raw, str) else None))

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(Application.rdn, ctx.base))
            previous = ctx.original_values().get(FLAGS_ATTR)
            ctx.values[FLAGS_ATTR] = encode_flags(
                ctx.values, previous if isinstance(previous, str) else None
            )


class WebApplication(ObjectType):
    """A web application (a link in the portal)."""

    name = "web_application"
    acl_category = "webApplication"
    label = _("Web application")
    label_plural = _("Web applications")
    nav = "secondary"
    nav_group = "settings"
    icon = "globe"
    category = "configuration"
    filter = f"(objectClass={WEB_CLASS})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=apps"
    columns = ("cn", "hrcApplicationTitle", "labeledURI")
    search_attrs = ("cn", "hrcApplicationTitle", "description", "labeledURI")

    class Main(Tab):
        name = "main"
        acl_key = "webApplication"
        label = _("Web application")
        object_classes = (WEB_CLASS,)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            StringAttr("hrcApplicationTitle", _("Title"), description=_("Name shown to users")),
            TextAttr("description", _("Description")),
            UrlAttr("labeledURI", _("Address"), required=True),
            ImageAttr("hrcApplicationImage", _("Icon"), max_size=(128, 128)),
            StringAttr(
                "hrcApplicationImageLocation",
                _("Icon address"),
                description=_("Address of an icon, used when no icon is uploaded"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(WebApplication.rdn, ctx.base))


# -------------------------------------------------------------- role tab


class ApplicationRefAttr(ObjectRefAttr):
    """DN of an application or of a web application."""

    def describe_extra(self) -> dict[str, JSON]:
        out = super().describe_extra()
        out["ref_types"] = ["application", "web_application"]
        return out


class ApplicationRightsTab(Tab):
    """Applications allowed for a role."""

    name = "applications"
    acl_key = "applicationRights"
    label = _("Applications")
    optional = True
    object_classes = (RIGHTS_CLASS,)

    allowed = Section(
        _("Applications"),
        ListAttr(
            "hrcApplicationAllowed",
            _("Applications allowed for this role"),
            ApplicationRefAttr("application", _("Application"), ref_type="application"),
            description=_("Desktop or web applications the occupants of the role may use"),
        ),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        wanted: Any = ctx.values.get("hrcApplicationAllowed")
        if not isinstance(wanted, list):
            return
        seen: set[str] = set()
        unique: list[str] = []
        for app_dn in wanted:  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(app_dn, str) or dnlib.normalize(app_dn) in seen:
                continue
            seen.add(dnlib.normalize(app_dn))
            unique.append(app_dn)
            entry = ctx.directory.get(app_dn, ["objectClass"])
            if entry is None or not (
                entry.has_object_class(DESKTOP_CLASS) or entry.has_object_class(WEB_CLASS)
            ):
                ctx.error("hrcApplicationAllowed", _("Not an application: {dn}").format(dn=app_dn))
                return
        ctx.values["hrcApplicationAllowed"] = unique or None


def plugin() -> Plugin:
    """Entry point of the applications plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(Application, WebApplication),
        tabs=(TabAttachment("role", ApplicationRightsTab),),
        settings=ApplicationsSettings(),
        api_routers=(build_router,),
    )


__all__ = [
    "FLAG_LETTERS",
    "Application",
    "ApplicationRefAttr",
    "ApplicationRightsTab",
    "ApplicationsSettings",
    "WebApplication",
    "allowed_applications",
    "decode_flags",
    "encode_flags",
    "plugin",
]
