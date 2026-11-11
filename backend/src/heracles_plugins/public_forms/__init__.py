"""Public forms plugin: create objects through a token-protected public page.

A ``publicForm`` (``publicForm/publicForm``, ``ou=forms``) describes which kind of
object the form creates (``hrcPublicFormTemplateType``, e.g. ``user``), an optional
template object whose values are copied, and, on the ``alteration`` tab
(``publicForm/publicFormAlteration``), which attributes visitors see.

Only attributes listed on the alteration tab can be set by visitors; every other
value comes from the template. Each alteration is ``<tab>.<attribute>`` plus:

* ``mandatory``: the visitor must provide a value;
* ``readonly``: shown, value taken from the template, cannot be changed;
* ``hidden``: not shown, value taken from the template;
* ``imported``: for an e-mail attribute, the invitee's address (from the
  invitation token) is used and cannot be changed.

Public endpoints: see :mod:`heracles_plugins.public_forms.router`. Private forms
require the personal token of an invitation
(:mod:`heracles_plugins.invitations`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from heracles.attributes import (
    BooleanAttr,
    CompositeAttr,
    DepartmentAttr,
    DisplayAttr,
    ListAttr,
    StringAttr,
    TextAttr,
    UrlAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab, UnknownTypeError
from heracles.objects.hooks import TabContext
from heracles_plugins.public_forms.captcha import Captcha
from heracles_plugins.public_forms.forms import (
    ALTERED_ATTR,
    FORM_CLASS,
    FieldRule,
    FormDefinition,
    FormError,
    FormPolicy,
    build_submission,
    describe_form,
    find_form,
    submit_form,
    usable_attribute,
)
from heracles_plugins.public_forms.router import build_public_router, build_router

PLUGIN_NAME = "public_forms"
NAME_RE = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"


@dataclass(slots=True)
class PublicFormsSettings:
    """Settings of the public forms plugin."""

    #: Show the definition of a private form (not the submission) without invitation token.
    allow_private_without_invitations: bool = False
    #: Secret signing captcha challenges (empty: random per process; set it when several
    #: workers serve the forms).
    captcha_secret: str = ""
    captcha_ttl_seconds: int = 600
    #: Successful submissions accepted per client address and hour.
    submissions_per_hour: int = 20
    max_body_bytes: int = 1_048_576
    #: Default container (documentation; the type fixes ``rdn`` today).
    forms_rdn: str = "ou=forms"


def _public_link(values: dict[str, Any]) -> str | None:
    name = values.get("cn")
    return f"/forms/{name}" if isinstance(name, str) and name else None


class PublicForm(ObjectType):
    """A public form."""

    name = "public_form"
    acl_category = "publicForm"
    label = _("Public form")
    label_plural = _("Public forms")
    icon = "clipboard-list"
    category = "workflow"
    filter = f"(objectClass={FORM_CLASS})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=forms"
    columns = ("cn", "hrcPublicFormTitle", "hrcPublicFormTemplateType")
    search_attrs = ("cn", "hrcPublicFormTitle")

    class Main(Tab):
        name = "main"
        acl_key = "publicForm"
        label = _("Public form")
        object_classes = (FORM_CLASS,)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            StringAttr("hrcPublicFormTitle", _("Title"), required=True),
            TextAttr("hrcPublicFormText", _("Introduction")),
            TextAttr(
                "hrcPublicFormFinalText",
                _("Final text"),
                description=_("Shown once the form was submitted"),
            ),
            DisplayAttr(
                "publicLink",
                _("Public address"),
                compute=_public_link,
                description=_("Path of the public page (invitations append the personal token)"),
            ),
        )
        target = Section(
            _("Created object"),
            StringAttr(
                "hrcPublicFormTemplateType",
                _("Object type"),
                required=True,
                description=_("Type of object created by the form, for instance user"),
            ),
            StringAttr(
                "hrcPublicFormTemplateDN",
                _("Template"),
                description=_("DN of an existing object whose values are copied (optional)"),
            ),
            BooleanAttr(
                "hrcPublicFormDefaultLocked",
                _("Lock created accounts"),
                description=_("New user accounts stay locked until an administrator unlocks them"),
                default=False,
            ),
        )
        access = Section(
            _("Access"),
            BooleanAttr(
                "hrcPublicFormPrivate",
                _("Private"),
                description=_("Only people with an invitation can submit the form"),
                default=False,
            ),
            BooleanAttr(
                "hrcPublicFormCaptcha",
                _("Ask a captcha"),
                default=False,
            ),
            UrlAttr("hrcPublicFormTosUrl", _("Terms of service address")),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            values = ctx.values
            type_name = values.get("hrcPublicFormTemplateType")
            if isinstance(type_name, str) and type_name:
                try:
                    info = ctx.registry.get(type_name)
                except UnknownTypeError:
                    ctx.error("hrcPublicFormTemplateType", _("Unknown object type."))
                    info = None
                template = values.get("hrcPublicFormTemplateDN")
                if info is not None and isinstance(template, str) and template:
                    entry = ctx.directory.get(template, ["objectClass"])
                    if entry is None or not all(
                        entry.has_object_class(c) for c in info.main_tab.object_classes
                    ):
                        ctx.error(
                            "hrcPublicFormTemplateDN",
                            _("The template is not an object of this type."),
                        )
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(PublicForm.rdn, ctx.base))

    class Alteration(Tab):
        name = "alteration"
        acl_key = "publicFormAlteration"
        label = _("Fields")
        # No objectClass of its own: always active, stored on the form entry.

        fields = Section(
            _("Fields"),
            ListAttr(
                ALTERED_ATTR,
                _("Fields shown to the visitor"),
                CompositeAttr(
                    ALTERED_ATTR,
                    _("Field"),
                    [
                        StringAttr(
                            "field",
                            _("Attribute"),
                            description=_("<tab>.<attribute>, for instance main.mail"),
                        ),
                        BooleanAttr("mandatory", _("Mandatory")),
                        BooleanAttr("readonly", _("Read only")),
                        BooleanAttr("imported", _("Imported from the invitation")),
                        BooleanAttr("hidden", _("Hidden")),
                    ],
                    separator="|",
                ),
                description=_(
                    "Only these attributes can be set by visitors; the others come from the "
                    "template"
                ),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            raw = ctx.values.get(ALTERED_ATTR)
            if not isinstance(raw, list) or not raw:
                return
            type_name = ctx.main_values().get("hrcPublicFormTemplateType")
            if not isinstance(type_name, str) or not type_name:
                return
            try:
                info = ctx.registry.get(type_name)
            except UnknownTypeError:
                return  # reported on the main tab
            seen: set[str] = set()
            for item in cast("list[object]", raw):
                entry = cast("dict[str, object]", item) if isinstance(item, dict) else {}
                value = entry.get("field")
                field = value if isinstance(value, str) else ""
                tab_name, _sep, attr_name = field.partition(".")
                tab = info.tab(tab_name)
                attr = tab.attribute(attr_name) if tab is not None else None
                if attr is None or not usable_attribute(attr):
                    ctx.error(
                        ALTERED_ATTR, _("Unknown or unusable attribute: {name}").format(name=field)
                    )
                    return
                if field in seen:
                    ctx.error(ALTERED_ATTR, _("Listed twice: {name}").format(name=field))
                    return
                seen.add(field)


def plugin() -> Plugin:
    """Entry point of the public forms plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(PublicForm,),
        settings=PublicFormsSettings(),
        public_routers=(build_router,),
    )


__all__ = [
    "Captcha",
    "FieldRule",
    "FormDefinition",
    "FormError",
    "FormPolicy",
    "PublicForm",
    "PublicFormsSettings",
    "build_public_router",
    "build_submission",
    "describe_form",
    "find_form",
    "plugin",
    "submit_form",
]
