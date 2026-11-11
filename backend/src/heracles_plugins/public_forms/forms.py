"""Public form logic: rules, definition, submission (framework independent)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from heracles.attributes import (
    JSON,
    AnyAttribute,
    DepartmentAttr,
    DisplayAttr,
)
from heracles.auth.passwords import lock
from heracles.core.containers import ensure_container
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, Entry, Modification, NoSuchObjectError, Scope
from heracles.ldap.filter import escape_filter_value
from heracles.objects import (
    ObjectNotFoundError,
    ObjectService,
    ObjectValidationError,
    TypeInfo,
    TypeRegistry,
    UnknownTypeError,
)
from heracles.objects.policy import TAB_ATTR
from heracles.objects.service import department_of
from heracles_plugins.invitations.tokens import (
    InvitationContext,
    claim_token,
    complete_registration,
    release_token,
)

FORM_CLASS = "hrcPublicForm"
FORMS_RDN = "ou=forms"
ALTERED_ATTR = "hrcPublicFormAlteredAttributes"
#: Tab of the invitations plugin that marks users created through a form.
REGISTRATION_TAB = "registration"


class FormError(Exception):
    """The form is misconfigured (unknown type, missing template, ...)."""


@dataclass(frozen=True, slots=True)
class FieldRule:
    """How one attribute of the created object is handled by the form."""

    tab: str
    attr: str
    mandatory: bool = False
    readonly: bool = False
    imported: bool = False
    hidden: bool = False

    @property
    def key(self) -> str:
        return f"{self.tab}.{self.attr}"


@dataclass(frozen=True, slots=True)
class FormDefinition:
    """A public form read from the directory."""

    dn: str
    name: str
    title: str
    text: str
    final_text: str
    type_name: str
    template_dn: str | None
    private: bool
    tos_url: str | None
    default_locked: bool
    captcha: bool
    rules: tuple[FieldRule, ...]

    @property
    def base(self) -> str:
        """Department in which the objects are created."""
        return department_of(self.dn, FORMS_RDN)


def _bool(entry: Entry, attr: str) -> bool:
    return (entry.text(attr) or "").upper() == "TRUE"


def parse_rules(values: list[str]) -> tuple[FieldRule, ...]:
    """Decode ``hrcPublicFormAlteredAttributes`` values (``tab.attr|M|R|I|H`` booleans)."""
    rules: list[FieldRule] = []
    for raw in values:
        parts = raw.split("|", 4)
        parts += [""] * (5 - len(parts))
        tab, _sep, attr = parts[0].partition(".")
        if not tab or not attr:
            continue
        flags = [p.strip().upper() == "TRUE" for p in parts[1:]]
        rules.append(FieldRule(tab, attr, *flags))
    return tuple(rules)


def form_from_entry(entry: Entry) -> FormDefinition:
    return FormDefinition(
        dn=entry.dn,
        name=entry.text("cn") or "",
        title=entry.text("hrcPublicFormTitle") or entry.text("cn") or "",
        text=entry.text("hrcPublicFormText") or "",
        final_text=entry.text("hrcPublicFormFinalText") or "",
        type_name=entry.text("hrcPublicFormTemplateType") or "",
        template_dn=entry.text("hrcPublicFormTemplateDN"),
        private=_bool(entry, "hrcPublicFormPrivate"),
        tos_url=entry.text("hrcPublicFormTosUrl"),
        default_locked=_bool(entry, "hrcPublicFormDefaultLocked"),
        captcha=_bool(entry, "hrcPublicFormCaptcha"),
        rules=parse_rules(entry.texts(ALTERED_ATTR)),
    )


def find_form(directory: DirectoryClient, name: str) -> FormDefinition | None:
    """The form called ``name`` (the first one in DN order when several departments have it)."""
    flt = f"(&(objectClass={FORM_CLASS})(cn={escape_filter_value(name)}))"
    try:
        found = sorted(directory.search(directory.base_dn, flt, Scope.SUBTREE), key=lambda e: e.dn)
    except NoSuchObjectError:
        return None
    return form_from_entry(found[0]) if found else None


# ------------------------------------------------------------------ fields


def _attribute(info: TypeInfo, rule: FieldRule) -> AnyAttribute | None:
    tab = info.tab(rule.tab)
    return tab.attribute(rule.attr) if tab is not None else None


def usable_attribute(attr: AnyAttribute) -> bool:
    """Can a form set this attribute? (not computed, not the department, not virtual-only)"""
    return not isinstance(attr, DisplayAttr | DepartmentAttr)


def _template_tabs(
    service: ObjectService, info: TypeInfo, template_dn: str
) -> dict[str, dict[str, Any]]:
    """Template object as ``tabs`` JSON (active optional tabs + stored, readable values)."""
    state = service.load(info.name, template_dn)
    out: dict[str, dict[str, Any]] = {}
    main_attr = info.type.main_attr
    for tab in info.tabs:
        tab_state = state.tabs.get(tab.name)
        if tab_state is None or not tab_state.active:
            continue
        values: dict[str, JSON] = {}
        for attr in tab.attributes():
            if (
                not attr.stored
                or attr.write_only
                or isinstance(attr, DisplayAttr | DepartmentAttr)
                or (tab is info.main_tab and attr.name == main_attr)
                or attr.name not in tab_state.values
            ):
                continue
            value = attr.to_json(tab_state.values[attr.name])
            if value is not None:
                values[attr.name] = value
        entry: dict[str, Any] = {"values": values}
        if tab.optional:
            entry["active"] = True
        out[tab.name] = entry
    return out


def template_tabs(
    directory: DirectoryClient, registry: TypeRegistry, form: FormDefinition
) -> dict[str, dict[str, Any]]:
    """Defaults provided by the form's template object (empty without template)."""
    if not form.template_dn:
        return {}
    info = registry.get(form.type_name)
    try:
        return _template_tabs(ObjectService(directory, registry), info, form.template_dn)
    except ObjectNotFoundError:
        raise FormError("The template of this form does not exist.") from None


def _initial(
    rule: FieldRule, attr: AnyAttribute, template: Mapping[str, Any], email: str | None
) -> tuple[JSON, bool]:
    """Initial JSON value of a field and whether the visitor cannot change it."""
    locked = rule.readonly or attr.readonly
    if rule.imported and attr.kind == "email" and email:
        return email, True
    tab = template.get(rule.tab)
    value: JSON = tab["values"].get(rule.attr) if tab is not None else None
    return value, locked


def describe_form(
    form: FormDefinition,
    info: TypeInfo,
    template: Mapping[str, Any],
    *,
    email: str | None = None,
) -> dict[str, Any]:
    """Public JSON of a form: texts and the fields to display."""
    fields: list[dict[str, Any]] = []
    for rule in form.rules:
        attr = _attribute(info, rule)
        if attr is None or rule.hidden or not usable_attribute(attr):
            continue
        value, locked = _initial(rule, attr, template, email)
        field = attr.describe()
        field.update(
            {
                "key": rule.key,
                "tab": rule.tab,
                "required": attr.required or rule.mandatory,
                "readonly": locked,
                "value": None if attr.write_only else value,
            }
        )
        fields.append(field)
    return {
        "name": form.name,
        "title": form.title,
        "text": form.text,
        "final_text": form.final_text,
        "private": form.private,
        "captcha": form.captcha,
        "tos_url": form.tos_url,
        "invitee_email": email,
        "fields": fields,
    }


# -------------------------------------------------------------- submission


@dataclass(slots=True)
class Submission:
    """A validated submission ready for :class:`ObjectService.create`."""

    tabs: dict[str, dict[str, Any]]
    writes: set[tuple[str, str]]


def build_submission(
    form: FormDefinition,
    info: TypeInfo,
    template: Mapping[str, Any],
    values: Mapping[str, Any],
    *,
    email: str | None = None,
) -> Submission:
    """Merge template defaults, imported values and the visitor's ``values`` (``tab.attr`` keys).

    Raises :class:`ObjectValidationError` for keys the form does not allow and for
    missing mandatory fields. Everything else is validated by the object service.
    """
    errors: dict[str, str] = {}
    tabs: dict[str, dict[str, Any]] = {
        name: {"values": dict(t["values"]), **({"active": True} if t.get("active") else {})}
        for name, t in template.items()
    }
    editable: dict[str, FieldRule] = {}
    for rule in form.rules:
        attr = _attribute(info, rule)
        if attr is None or not usable_attribute(attr):
            continue
        tab = tabs.setdefault(rule.tab, {"values": {}})
        tab_cls = info.tab(rule.tab)
        if tab_cls is not None and tab_cls.optional:
            tab["active"] = True
        imported, locked = _initial(rule, attr, template, email)
        if rule.imported and attr.kind == "email" and email:
            tab["values"][rule.attr] = imported
        if not (rule.hidden or locked):
            editable[rule.key] = rule
    for key, raw in values.items():
        rule = editable.get(key)
        if rule is None:
            errors[key] = "This field is not accepted by the form."
            continue
        tabs[rule.tab]["values"][rule.attr] = raw
    for key, rule in editable.items():
        attr = _attribute(info, rule)
        present = tabs[rule.tab]["values"].get(rule.attr)
        if (
            attr is not None
            and (rule.mandatory or attr.required)
            and present in (None, "", [])
            and key not in errors
        ):
            errors[key] = "This field is required."
    if errors:
        raise ObjectValidationError(errors)
    if info.name == "user" and info.tab(REGISTRATION_TAB) is not None:
        tabs.setdefault(REGISTRATION_TAB, {"values": {}})["active"] = True
    writes: set[tuple[str, str]] = set()
    for tab_name, tab in tabs.items():
        writes.update((tab_name, a) for a in tab["values"])
        if tab.get("active"):
            writes.add((tab_name, TAB_ATTR))
    return Submission(tabs, writes)


class FormPolicy:
    """Access policy of a submission: create one object type, write the chosen attributes."""

    def __init__(self, type_name: str, base: str, writes: set[tuple[str, str]]) -> None:
        self._type = type_name
        self._base = dnlib.normalize(base)
        self._writes = writes

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return False

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return (tab, attr) in self._writes

    def can_create(self, type_name: str, base: str) -> bool:
        return type_name == self._type and dnlib.normalize(base) == self._base

    def can_delete(self, dn: str, type_name: str) -> bool:
        return False


def lock_user(directory: DirectoryClient, registry: TypeRegistry, dn: str) -> None:
    """Lock the account of ``dn`` (like the console does), including plugin lock hooks."""
    entry = directory.get(dn)
    if entry is None:
        return
    stored = entry.text("userPassword") or ""
    new = lock(stored)
    changes: list[Modification] = []
    if new != stored:
        changes.append(Modification("replace", "userPassword", [new.encode()]))
    for hook in registry.account_lock_hooks:
        changes.extend(hook(entry, True))
    if changes:
        directory.modify(dn, changes)


def submit_form(
    directory: DirectoryClient,
    registry: TypeRegistry,
    form: FormDefinition,
    values: Mapping[str, Any],
    *,
    context: InvitationContext | None,
    now: datetime,
) -> str:
    """Create the object described by ``values``; returns its DN.

    Raises :class:`ObjectValidationError` on invalid input, :class:`FormError`
    when the form is misconfigured and :class:`InvitationUsedError` when the invitation
    token was already consumed.
    """
    try:
        info = registry.get(form.type_name)
    except UnknownTypeError:
        raise FormError("The object type of this form is not available.") from None
    template = template_tabs(directory, registry, form)
    email = context.email if context is not None else None
    submission = build_submission(form, info, template, values, email=email)
    policy = FormPolicy(info.name, form.base, submission.writes)
    if info.type.rdn:
        ensure_container(directory, dnlib.join(info.type.rdn, form.base))
    service = ObjectService(directory, registry, policy=policy)
    # The token is consumed before anything is written, so concurrent submissions with one
    # invitation cannot both create an object; a failed creation gives it back.
    claimed = claim_token(directory, context) if context is not None else None
    try:
        dn = service.create(info.name, form.base, submission.tabs)
    except BaseException:
        if claimed is not None:
            release_token(directory, claimed)
        raise
    if form.default_locked and info.name == "user":
        lock_user(directory, registry, dn)
    if context is not None:
        complete_registration(directory, context, dn, now)
    return dn


__all__ = [
    "ALTERED_ATTR",
    "FORMS_RDN",
    "FORM_CLASS",
    "FieldRule",
    "FormDefinition",
    "FormError",
    "FormPolicy",
    "Submission",
    "build_submission",
    "describe_form",
    "find_form",
    "form_from_entry",
    "lock_user",
    "parse_rules",
    "submit_form",
    "template_tabs",
    "usable_attribute",
]
