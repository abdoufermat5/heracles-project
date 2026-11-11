"""Sudo plugin: ``sudoRole`` entries (users, hosts, commands and sudoers options)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from heracles.attributes import (
    BooleanAttr,
    DateTimeAttr,
    DepartmentAttr,
    IntAttr,
    ListAttr,
    StringAttr,
    TextAttr,
)
from heracles.i18n import _
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins.sudo.options import OPTIONS, OptionSpec, option_error, parse_option
from heracles_plugins.sudo.syntax import (
    command_error,
    host_error,
    runas_group_error,
    runas_user_error,
    user_error,
)

PLUGIN_NAME = "sudo"
DEFAULTS_CN = "defaults"
CN_RE = r"[^\s,]+"


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


class CheckedStringAttr(StringAttr):
    """A string whose syntax is checked by ``checker`` (returns a message or ``None``)."""

    def __init__(
        self,
        name: str,
        label: str,
        checker: Callable[[str], str | None],
        **kwargs: Any,
    ) -> None:
        super().__init__(name, label, **kwargs)
        self.checker = checker

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        message = self.checker(value)
        if message is not None:
            errors.append(message)
        return errors


class SudoRole(ObjectType):
    """A sudo role (``sudoRole``)."""

    name = "sudo"
    acl_category = "sudo"
    label = _("Sudo role")
    label_plural = _("Sudo roles")
    nav = "primary"
    nav_group = "access"
    icon = "shield-check"
    category = "access"
    filter = "(objectClass=sudoRole)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=sudoers"
    columns = ("cn", "description", "sudoUser", "sudoHost")
    search_attrs = ("cn", "description", "sudoUser", "sudoHost")

    class Main(Tab):
        name = "main"
        acl_key = "sudo"
        label = _("Role settings")
        object_classes = ("sudoRole",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=CN_RE),
            TextAttr("description", _("Description")),
            virtual(
                BooleanAttr(
                    "is_default",
                    _("Global defaults"),
                    description=_("Holds the global options (the role is named 'defaults')"),
                    default=False,
                )
            ),
            IntAttr("sudoOrder", _("Priority"), min=0),
            DateTimeAttr("sudoNotBefore", _("Valid from")),
            DateTimeAttr("sudoNotAfter", _("Valid until")),
        )
        who = Section(
            _("Who"),
            ListAttr(
                "sudoUser",
                _("Users"),
                CheckedStringAttr("sudoUser", _("User"), user_error),
                description=_("Login, %group, %#gid, #uid, +netgroup or ALL; '!' negates"),
            ),
            ListAttr(
                "sudoHost",
                _("Hosts"),
                CheckedStringAttr("sudoHost", _("Host"), host_error),
                description=_("Host name, IP, network (CIDR) or ALL; '!' negates"),
                default=["ALL"],
            ),
        )
        what = Section(
            _("What"),
            ListAttr(
                "sudoCommand",
                _("Commands"),
                CheckedStringAttr("sudoCommand", _("Command"), command_error),
                description=_("Command with optional arguments, or ALL; '!' negates"),
            ),
            ListAttr(
                "sudoRunAsUser",
                _("Run as users"),
                CheckedStringAttr("sudoRunAsUser", _("User"), runas_user_error),
            ),
            ListAttr(
                "sudoRunAsGroup",
                _("Run as groups"),
                CheckedStringAttr("sudoRunAsGroup", _("Group"), runas_group_error),
            ),
        )

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            ctx.values["is_default"] = ctx.values.get("cn") == DEFAULTS_CN

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            values = ctx.values
            wants_default = bool(values.get("is_default"))
            if wants_default:
                if ctx.creating:
                    values["cn"] = DEFAULTS_CN
                elif ctx.was_touched("is_default") and values.get("cn") != DEFAULTS_CN:
                    ctx.error(
                        "is_default", _("Only a role named 'defaults' can hold the defaults.")
                    )
            start = values.get("sudoNotBefore")
            end = values.get("sudoNotAfter")
            if start is not None and end is not None and end <= start:
                ctx.error("sudoNotAfter", _("Must be after the start of the validity."))

    class Options(Tab):
        name = "options"
        acl_key = "sudoOption"
        label = _("Options")
        object_classes = ("sudoRole",)

        options = Section(
            _("Options"),
            ListAttr(
                "sudoOption",
                _("Options"),
                CheckedStringAttr(
                    "sudoOption",
                    _("Option"),
                    option_error,
                    description=_("name, !name or name=value"),
                ),
            ),
        )


def plugin() -> Plugin:
    """Entry point of the sudo plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(SudoRole,),
        required_object_classes=("sudoRole",),
    )


__all__ = [
    "DEFAULTS_CN",
    "OPTIONS",
    "CheckedStringAttr",
    "OptionSpec",
    "SudoRole",
    "option_error",
    "parse_option",
    "plugin",
]
