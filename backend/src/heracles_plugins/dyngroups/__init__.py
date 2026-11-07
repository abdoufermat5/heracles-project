"""Dynamic groups plugin: the members of a group are computed from a rule.

Adds the optional ``dynamic`` tab to the ``group`` type (ACL key
``ogroup/dynamicGroup``). The rule is stored in ``memberURL`` (an LDAP filter or
an LDAP URL, see :mod:`heracles_plugins.dyngroups.membership`); on every save
the matching users are written to ``member`` so that the entry stays a valid
``groupOfNames``. :func:`refresh_dynamic_groups` recomputes every dynamic group
and is meant for a periodic job.
"""

from __future__ import annotations

from dataclasses import dataclass

from heracles.attributes import ListAttr, ObjectRefAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, DirectoryError, Modification, NoSuchObjectError
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.dyngroups.membership import (
    DEFAULT_MAX_MEMBERS,
    MemberRule,
    MemberRuleError,
    evaluate_members,
    parse_member_rule,
    select_members,
)

PLUGIN_NAME = "dyngroups"
CLASSES = ("groupOfURLs", "extensibleObject")


@dataclass(slots=True)
class DynGroupsSettings:
    """Settings of the dynamic groups plugin."""

    #: A rule matching more users than this is refused.
    max_members: int = DEFAULT_MAX_MEMBERS


def settings_of(ctx: TabContext) -> DynGroupsSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, DynGroupsSettings) else DynGroupsSettings()


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


class MemberRuleAttr(StringAttr):
    """A membership rule (LDAP filter or LDAP URL), validated on input."""

    def _validate(self, value: str) -> list[str]:
        errors = super()._validate(value)
        try:
            parse_member_rule(value)
        except MemberRuleError as exc:
            errors.append(_(str(exc)))
        return errors


class DynamicGroupTab(Tab):
    """Members computed from an LDAP URL or filter."""

    name = "dynamic"
    acl_key = "dynamicGroup"
    label = _("Dynamic membership")
    optional = True
    object_classes = CLASSES

    rule = Section(
        _("Rule"),
        MemberRuleAttr(
            "memberURL",
            _("Membership rule"),
            required=True,
            description=_(
                "An LDAP filter such as (departmentNumber=sales), or an LDAP URL such as "
                "ldap:///ou=people,dc=example,dc=com??sub?(l=Paris). Only users are members."
            ),
        ),
    )
    computed = Section(
        _("Current members"),
        virtual(
            ListAttr(
                "computedMembers",
                _("Members"),
                ObjectRefAttr("computedMember", _("Member"), ref_type="user"),
                readonly=True,
                description=_("Users currently matching the rule (updated on save)"),
            )
        ),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        rule = ctx.values.get("memberURL")
        members: list[str] = []
        if isinstance(rule, str) and rule:
            try:
                members = evaluate_members(
                    ctx.directory, rule, max_members=settings_of(ctx).max_members
                )
            except (MemberRuleError, DirectoryError):
                members = []
        ctx.values["computedMembers"] = members or None

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        rule = ctx.values.get("memberURL")
        if not isinstance(rule, str) or not rule:
            return  # reported as required by the validation
        try:
            members = evaluate_members(
                ctx.directory, rule, max_members=settings_of(ctx).max_members
            )
        except MemberRuleError as exc:
            ctx.error("memberURL", _(str(exc)))
            return
        if not members:
            ctx.error(
                "memberURL",
                _("The rule matches no user; a group needs at least one member."),
            )
            return
        ctx.values["computedMembers"] = members
        ctx.tabs[ctx.info.main_tab.name].values["member"] = members


def refresh_dynamic_groups(
    directory: DirectoryClient, *, max_members: int = DEFAULT_MAX_MEMBERS
) -> dict[str, int]:
    """Recompute ``member`` of every dynamic group; returns ``{group DN: member count}``.

    Only groups whose membership changed are written. Groups with an invalid rule
    or an empty result are left untouched.
    """
    flt = "(&(objectClass=groupOfNames)(objectClass=groupOfURLs)(memberURL=*))"
    changed: dict[str, int] = {}
    try:
        groups = list(directory.search(directory.base_dn, flt, attrs=["member", "memberURL"]))
    except NoSuchObjectError:
        return changed
    for group in groups:
        rule = group.text("memberURL")
        if rule is None:
            continue
        try:
            members = evaluate_members(directory, rule, max_members=max_members)
        except (MemberRuleError, DirectoryError):
            continue
        current = sorted(m.lower() for m in group.texts("member"))
        if not members or sorted(m.lower() for m in members) == current:
            continue
        directory.modify(
            group.dn, [Modification("replace", "member", [m.encode() for m in members])]
        )
        changed[group.dn] = len(members)
    return changed


def plugin() -> Plugin:
    """Entry point of the dynamic groups plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("group", DynamicGroupTab),),
        settings=DynGroupsSettings(),
    )


__all__ = [
    "DynGroupsSettings",
    "DynamicGroupTab",
    "MemberRule",
    "MemberRuleError",
    "evaluate_members",
    "parse_member_rule",
    "plugin",
    "refresh_dynamic_groups",
    "select_members",
]
