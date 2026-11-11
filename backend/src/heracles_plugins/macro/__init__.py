"""Macro plugin: telephony macros object type and user macro assignment tab."""

from __future__ import annotations

from dataclasses import dataclass

from heracles.attributes import DepartmentAttr, StringAttr, TextAttr
from heracles.i18n import _
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "macro"


@dataclass(slots=True)
class MacroSettings:
    """Settings of the macro plugin."""

    attribute_class: str = ""
    attribute_description: str = ""
    attribute_label: str = ""


class PhoneMacro(ObjectType):
    """Telephony macro object type."""

    name = "phone_macro"
    acl_category = "phoneMacro"
    label = _("Phone macro")
    label_plural = _("Phone macros")
    icon = "phone"
    category = "systems"
    rdn = "ou=macros,ou=asterisk,ou=configs,ou=systems"
    main_attr = "cn"
    name_attr = "cn"
    filter = "(objectClass=hrcPhoneMacro)"
    columns = ("cn", "description")
    search_attrs = ("cn", "description")
    required_object_classes = ("top",)

    class Main(Tab):
        name = "main"
        acl_key = "phoneMacro"
        label = _("Phone macro")
        object_classes = ("hrcPhoneMacro",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr(
                "cn",
                _("Macro name"),
                required=True,
                pattern=r"[A-Za-z0-9_][A-Za-z0-9_.-]*",
            ),
            TextAttr("description", _("Description")),
            TextAttr(
                "hrcMacroAction",
                _("Macro action"),
                description=_("Macro dialplan commands or actions"),
            ),
        )


class MacroTab(Tab):
    """User telephony macro tab."""

    name = "macro"
    acl_key = "Macro"
    label = _("Macro")
    description = _("Telephony macro: quick-dial actions")
    object_classes = ("hrcPhoneMacroUser",)
    optional = True

    macros = Section(
        _("Macros"),
        StringAttr(
            "hrcPhoneMacroContent",
            _("Phone macro"),
            description=_("Telephony macro assigned to this user"),
        ),
        StringAttr(
            "hrcPhoneMacroParameter",
            _("Macro parameter"),
            description=_("Parameters passed to the macro"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the macro plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(PhoneMacro,),
        tabs=(TabAttachment("user", MacroTab),),
        required_object_classes=(),
        settings=MacroSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "MacroSettings",
    "MacroTab",
    "PhoneMacro",
    "plugin",
]
