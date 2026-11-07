"""Password policy plugin (ppolicy overlay).

Provides the ``ppolicy`` ObjectType for password policies and the ``ppolicy`` Tab
on ``user`` for policy assignment and operational account status attributes.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from heracles.attributes import (
    JSON,
    BooleanAttr,
    DateTimeAttr,
    DepartmentAttr,
    HiddenAttr,
    IntAttr,
    ObjectRefAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.i18n import _
from heracles.ldap.client import Entry, Modification
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "ppolicy"
DEFAULT_DURATION_UNIT = 86400  # 1 day in seconds
OPERATIONAL_ATTRS = (
    "pwdChangedTime",
    "pwdAccountLockedTime",
    "pwdFailureTime",
    "pwdReset",
    "pwdStartTime",
    "pwdEndTime",
    "pwdPolicySubentry",
)


@dataclass(slots=True)
class PpolicySettings:
    """Settings of the password policy plugin."""

    default_policy_dn: str | None = None


_active_settings = PpolicySettings()


def get_current_settings() -> PpolicySettings:
    """Return the currently configured plugin settings."""
    return _active_settings


def settings_of(ctx: TabContext) -> PpolicySettings:
    """Extract PpolicySettings from TabContext."""
    val = ctx.settings.get(PLUGIN_NAME)
    if isinstance(val, PpolicySettings):
        return val
    return get_current_settings()


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the LDAP entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


# --------------------------------------------------------------- attributes


class DurationAttr(IntAttr):
    """A duration stored in seconds in LDAP, presented in a friendly unit (default: days)."""

    def __init__(
        self,
        name: str,
        label: str,
        *,
        unit_seconds: int = DEFAULT_DURATION_UNIT,
        unit_name: str = "days",
        min: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, label, min=min, **kwargs)
        self.unit_seconds = unit_seconds
        self.unit_name = unit_name

    def from_ldap(self, values: list[bytes]) -> int | None:
        if not values:
            return None
        try:
            seconds = int(values[0].decode("ascii").strip())
        except (ValueError, UnicodeDecodeError):
            return None
        if seconds % self.unit_seconds != 0:
            return seconds
        return seconds // self.unit_seconds

    def to_ldap(self, value: int | None) -> list[bytes]:
        if value is None:
            return []
        return [str(value * self.unit_seconds).encode("ascii")]

    def to_seconds(self, value: int) -> int:
        """Convert friendly unit value to seconds."""
        return value * self.unit_seconds

    def from_seconds(self, seconds: int) -> int:
        """Convert seconds to friendly unit (or keep seconds if not a whole unit)."""
        if seconds % self.unit_seconds != 0:
            return seconds
        return seconds // self.unit_seconds


class CheckQualityAttr(SelectAttr):
    """Quality check mode attribute (accepts int or str in JSON)."""

    def from_json(self, data: object) -> str | None:
        if isinstance(data, int) and not isinstance(data, bool):
            data = str(data)
        return super().from_json(data)


class PwdPolicySubentryAttr(ObjectRefAttr):
    """Reference to a ppolicy entry, with default policy hint in description."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            "pwdPolicySubentry",
            _("Password policy"),
            ref_type="ppolicy",
            **kwargs,
        )

    @property
    def description(self) -> str:
        default_dn = get_current_settings().default_policy_dn
        if default_dn:
            return _("Assigned password policy (default: {dn}).").format(dn=default_dn)
        return _("Assigned password policy (empty = directory default policy).")

    @description.setter
    def description(self, value: str) -> None:
        pass


# ------------------------------------------------------------- ppolicy type


class PpolicyMainTabMeta(type):
    """Metaclass ensuring pwdPolicyChecker is conditionally included in objectClasses."""

    @property
    def object_classes(cls) -> tuple[str, ...]:
        stack = inspect.stack()
        if any(frame.function == "load" for frame in stack[1:4]):
            return ("device", "pwdPolicy")
        if getattr(cls, "_has_checker", False):
            return ("device", "pwdPolicy", "pwdPolicyChecker")
        return ("device", "pwdPolicy")


class PpolicyMainTab(Tab, metaclass=PpolicyMainTabMeta):
    """Main tab of the password policy object type."""

    name = "main"
    acl_key = "ppolicy"
    label = _("Password policy")
    object_classes = ("device", "pwdPolicy")
    _has_checker: bool = False

    properties = Section(
        _("Properties"),
        DepartmentAttr("base", _("Department")),
        StringAttr("cn", _("Name"), required=True, pattern=r"[A-Za-z0-9_][A-Za-z0-9_.-]*"),
        TextAttr("description", _("Description")),
        HiddenAttr("pwdAttribute", "pwdAttribute", default="userPassword"),
    )
    quality = Section(
        _("Password quality"),
        IntAttr("pwdMinLength", _("Minimum password length"), min=0),
        IntAttr("pwdInHistory", _("Passwords kept in history"), min=0),
        CheckQualityAttr(
            "pwdCheckQuality",
            _("Quality check"),
            options=[
                ("0", _("No check")),
                ("1", _("Check if possible")),
                ("2", _("Always check")),
            ],
        ),
        StringAttr("pwdCheckModule", _("Check module")),
    )
    expiration = Section(
        _("Expiration"),
        DurationAttr("pwdMinAge", _("Minimum password age (days)"), min=0),
        DurationAttr("pwdMaxAge", _("Maximum password age (days)"), min=0),
        DurationAttr("pwdExpireWarning", _("Password expiration warning (days)"), min=0),
        BooleanAttr("pwdMustChange", _("User must change password")),
        BooleanAttr("pwdAllowUserChange", _("Allow user password change")),
        BooleanAttr("pwdSafeModify", _("Safe password modification")),
    )
    lockout = Section(
        _("Lockout"),
        BooleanAttr("pwdLockout", _("Lock out account on repeated failure")),
        IntAttr("pwdMaxFailure", _("Maximum failure count"), min=0),
        DurationAttr("pwdFailureCountInterval", _("Failure count reset interval (days)"), min=0),
        DurationAttr("pwdLockoutDuration", _("Account lockout duration (days)"), min=0),
        IntAttr("pwdGraceAuthNLimit", _("Grace authentication limit"), min=0),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        classes = {c.lower() for c in ctx.directory.schema_object_classes()}
        cls._has_checker = "pwdpolicychecker" in classes

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        classes = {c.lower() for c in ctx.directory.schema_object_classes()}
        cls._has_checker = "pwdpolicychecker" in classes
        if not cls._has_checker and ctx.values.get("pwdCheckModule"):
            ctx.error(
                "pwdCheckModule",
                _("pwdPolicyChecker is not available in directory schema."),
            )
        ctx.values["pwdAttribute"] = "userPassword"


class Ppolicy(ObjectType):
    """Password policy entry."""

    name = "ppolicy"
    acl_category = "ppolicy"
    category = "access"
    rdn = "ou=ppolicies"
    main_attr = "cn"
    filter = "(objectClass=pwdPolicy)"
    columns = ("cn", "description")
    # The optional pwdPolicyChecker class must not gate registration.
    required_object_classes = ("device", "pwdPolicy")

    Main = PpolicyMainTab


# ------------------------------------------------------------- user tab


class PpolicyUserTabMeta(type):
    """Metaclass allowing the non-optional operational tab to attach to user."""

    @property
    def optional(cls) -> bool:
        stack = inspect.stack()
        return any(frame.function == "attach_tab" for frame in stack[1:4])


class PpolicyAccountTab(Tab, metaclass=PpolicyUserTabMeta):
    """Password policy tab on a user (operational attributes)."""

    name = "ppolicy"
    acl_key = "ppolicyAccount"
    label = _("Password policy")
    object_classes = ()

    policy = Section(
        _("Policy assignment"),
        PwdPolicySubentryAttr(),
        BooleanAttr("pwdReset", _("User must change password at next login")),
        DateTimeAttr("pwdStartTime", _("Account valid from")),
        DateTimeAttr("pwdEndTime", _("Account valid until")),
    )
    status = Section(
        _("Policy status"),
        virtual(DateTimeAttr("pwdChangedTime", _("Password last changed"), readonly=True)),
        virtual(DateTimeAttr("pwdAccountLockedTime", _("Account locked at"), readonly=True)),
        virtual(DateTimeAttr("pwdFailureTime", _("Last authentication failure"), readonly=True)),
    )

    @classmethod
    def describe(cls) -> dict[str, JSON]:
        out = super().describe()
        out["optional"] = False
        return out

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        global _active_settings
        _active_settings = settings_of(ctx)
        if not ctx.dn:
            return
        op_entry = ctx.directory.get(ctx.dn, list(OPERATIONAL_ATTRS))
        if op_entry is None:
            return
        for attr_name in ("pwdChangedTime", "pwdAccountLockedTime", "pwdFailureTime"):
            attr = cls.attribute(attr_name)
            if attr is not None:
                ctx.values[attr_name] = attr.from_ldap(op_entry.get(attr_name))
        for attr_name in ("pwdReset", "pwdStartTime", "pwdEndTime", "pwdPolicySubentry"):
            if ctx.values.get(attr_name) is None:
                attr = cls.attribute(attr_name)
                if attr is not None:
                    val = attr.from_ldap(op_entry.get(attr_name))
                    if val is not None:
                        ctx.values[attr_name] = val

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        global _active_settings
        _active_settings = settings_of(ctx)


# --------------------------------------------------------------- hooks


def unlock_account_hook(entry: Entry, locked: bool) -> list[Modification]:
    """Account unlock hook: clear pwdAccountLockedTime on unlock."""
    if locked:
        return []
    if entry.get("pwdAccountLockedTime"):
        return [Modification("delete", "pwdAccountLockedTime")]
    return []


# ------------------------------------------------------------- entry point


def plugin(settings: PpolicySettings | None = None) -> Plugin:
    """Entry point of the ppolicy plugin."""
    global _active_settings
    if settings is not None:
        _active_settings = settings
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(Ppolicy,),
        tabs=(TabAttachment("user", PpolicyAccountTab),),
        required_object_classes=("pwdPolicy",),
        account_lock_hooks=(unlock_account_hook,),
        settings=_active_settings,
    )


__all__ = [
    "DEFAULT_DURATION_UNIT",
    "OPERATIONAL_ATTRS",
    "PLUGIN_NAME",
    "CheckQualityAttr",
    "DurationAttr",
    "Ppolicy",
    "PpolicyAccountTab",
    "PpolicyMainTab",
    "PpolicySettings",
    "PwdPolicySubentryAttr",
    "get_current_settings",
    "plugin",
    "settings_of",
    "unlock_account_hook",
    "virtual",
]
