"""Personal plugin: extra personal information on users (``hrcPersonalInfo``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from heracles.attributes import (
    AnyAttribute,
    BooleanAttr,
    CompositeAttr,
    DateAttr,
    DisplayAttr,
    EmailAttr,
    ListAttr,
    SelectAttr,
    StringAttr,
)
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "personal"

GENDERS = (
    ("", _("None")),
    ("M", _("Male")),
    ("F", _("Female")),
)

SOCIAL_SITES = (
    ("facebook", _("Facebook")),
    ("twitter", _("Twitter")),
    ("diaspora", _("Diaspora")),
    ("linkedin", _("LinkedIn")),
    ("github", _("GitHub")),
    ("googlescholar", _("Google Scholar")),
    ("matrix", _("Matrix")),
)

_GITHUB_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_TWITTER_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_LINKEDIN_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_MATRIX_RE = re.compile(r"^@[A-Za-z0-9._=\-/+]+:[A-Za-z0-9.\-]+(?::\d+)?$")
_DIASPORA_RE = re.compile(r"^[A-Za-z0-9._\-]+@[A-Za-z0-9.\-]+(?::\d+)?$")


@dataclass(slots=True)
class PersonalSettings:
    """Settings of the personal plugin."""

    private_mail_for_password_recovery: bool = False
    """When enabled, self-service password recovery may look up ``hrcPrivateMail``
    addresses in addition to the primary ``mail`` attribute. Currently reserved
    for future password recovery flows.
    """


def settings_of(ctx: TabContext) -> PersonalSettings:
    """Return the PersonalSettings configured in the context registry."""
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, PersonalSettings) else PersonalSettings()


def today() -> date:
    """Return the current date (extracted for testability)."""
    return date.today()


def virtual[A: AnyAttribute](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False
    return attr


# --------------------------------------------------------------- attributes


class DateOfBirthAttr(DateAttr):
    """Calendar date of birth stored as plain text YYYY-MM-DD (must be in the past)."""

    def from_ldap(self, values: list[bytes]) -> date | None:
        if not values:
            return None
        text = values[0].decode("ascii", errors="replace").strip()
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    def to_ldap(self, value: date | None) -> list[bytes]:
        if value is None:
            return []
        return [value.isoformat().encode("ascii")]

    def _validate(self, value: date) -> list[str]:
        errors = super()._validate(value)
        if value >= today():
            errors.append(_("Date of birth must be in the past."))
        return errors


def validate_social_account(site: str, account_id: str) -> str | None:
    """Return a validation error message if the account id is invalid for the site, else None."""
    if not account_id or not account_id.strip():
        return _("Identifier must not be empty.")
    if account_id.strip() != account_id or any(c.isspace() for c in account_id):
        return _("Identifier must not contain spaces.")

    match site:
        case "github":
            if not _GITHUB_RE.fullmatch(account_id):
                return _("Invalid GitHub username.")
        case "twitter":
            if not _TWITTER_RE.fullmatch(account_id):
                return _("Invalid Twitter username.")
        case "linkedin":
            if not _LINKEDIN_RE.fullmatch(account_id):
                return _("Invalid LinkedIn profile ID.")
        case "matrix":
            if not _MATRIX_RE.fullmatch(account_id):
                return _("Invalid Matrix ID (expected '@user:server').")
        case "diaspora":
            if not _DIASPORA_RE.fullmatch(account_id):
                return _("Invalid Diaspora handle (expected 'user@pod').")
        case _:
            if ":" in account_id:
                return _("Identifier must not contain ':'.")
    return None


def profile_url(site: str, account_id: str) -> str | None:
    """Build a public profile URL for a given social account."""
    acc_id = account_id.strip()
    match site:
        case "github":
            return f"https://github.com/{acc_id}"
        case "twitter":
            return f"https://twitter.com/{acc_id.removeprefix('@')}"
        case "linkedin":
            return f"https://www.linkedin.com/in/{acc_id}"
        case "facebook":
            return f"https://www.facebook.com/{acc_id}"
        case "googlescholar":
            return f"https://scholar.google.com/citations?user={acc_id}"
        case "matrix":
            return f"https://matrix.to/#/{acc_id}"
        case "diaspora":
            user, sep, pod = acc_id.partition("@")
            if sep and pod:
                return f"https://{pod}/u/{user}"
            return f"https://diasp.org/u/{acc_id}"
        case _:
            return None


def social_urls(values: dict[str, Any]) -> str | None:
    """Format profile URLs of configured social accounts."""
    raw = values.get("hrcSocialAccount")
    if not isinstance(raw, list):
        return None
    urls: list[str] = []
    for item in cast("list[object]", raw):
        if isinstance(item, dict):
            entry = cast("dict[str, object]", item)
            site = entry.get("site")
            account_id = entry.get("id")
            if isinstance(site, str) and isinstance(account_id, str):
                url = profile_url(site, account_id)
                if url:
                    urls.append(url)
    return "\n".join(urls) or None


class SocialAccountAttr(CompositeAttr):
    """Composite attribute for a social account (site + identifier)."""

    def __init__(
        self,
        name: str = "socialAccount",
        label: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name,
            label or _("Social account"),
            fields=(
                SelectAttr("site", _("Platform"), options=SOCIAL_SITES, required=True),
                StringAttr("id", _("Identifier"), required=True),
            ),
            separator=":",
            **kwargs,
        )

    def _validate(self, value: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        site_field = self.fields[0]
        id_field = self.fields[1]
        site = value.get(site_field.name)
        acc_id = value.get(id_field.name)

        site_errors = site_field.validate(site)
        if site_errors:
            errors.extend(f"{site_field.label}: {m}" for m in site_errors)
        elif self.separator in self._pack_field(site_field, site):
            errors.append(
                _("{label}: must not contain '{sep}'.").format(
                    label=site_field.label, sep=self.separator
                )
            )

        id_errors = id_field.validate(acc_id)
        if id_errors:
            errors.extend(f"{id_field.label}: {m}" for m in id_errors)

        if not errors and isinstance(site, str) and isinstance(acc_id, str):
            problem = validate_social_account(site, acc_id)
            if problem:
                errors.append(f"{id_field.label}: {problem}")

        return errors


# --------------------------------------------------------------------- tabs


class PersonalTab(Tab):
    """Extra personal information on a user."""

    name = "personal"
    label = _("Personal")
    description = _("Personal details: private contact data and preferences")
    acl_key = "personalInfo"
    optional = True
    object_classes = ("hrcPersonalInfo",)

    personal_info = Section(
        _("Personal information"),
        StringAttr("personalTitle", _("Personal title")),
        StringAttr("hrcNickName", _("Nickname")),
        StringAttr("hrcBadge", _("Badge number"), description=_("Badge number")),
        DateOfBirthAttr(
            "hrcDateOfBirth",
            _("Date of birth"),
            description=_("Date of birth (YYYY-MM-DD)"),
        ),
        SelectAttr("hrcGender", _("Gender"), options=GENDERS, default=""),
        StringAttr("co", _("Country")),
        DateAttr("hrcContractStartDate", _("Contract start date")),
        DateAttr("hrcContractEndDate", _("Contract end date")),
        BooleanAttr(
            "hrcPhotoVisible",
            _("Photo visible in external tools"),
            default=True,
        ),
    )
    contact = Section(
        _("Contact"),
        ListAttr(
            "hrcSocialAccount",
            _("Social accounts"),
            SocialAccountAttr("socialAccount", _("Social account")),
        ),
        ListAttr(
            "hrcPrivateMail",
            _("Private email addresses"),
            EmailAttr("mail", _("Email")),
        ),
        virtual(
            DisplayAttr(
                "socialUrls",
                _("Profile URLs"),
                compute=social_urls,
                description=_("Public profile links derived from social accounts"),
            )
        ),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        start = ctx.values.get("hrcContractStartDate")
        end = ctx.values.get("hrcContractEndDate")
        if isinstance(start, date) and isinstance(end, date) and end < start:
            ctx.error(
                "hrcContractEndDate",
                _("Contract end date must be on or after start date."),
            )

    @classmethod
    def compute(cls, values: dict[str, Any]) -> None:
        values["socialUrls"] = social_urls(values)

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        ctx.values["socialUrls"] = social_urls(ctx.values)


def plugin() -> Plugin:
    """Entry point of the personal plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", PersonalTab),),
        required_object_classes=("hrcPersonalInfo",),
        settings=PersonalSettings(),
    )


__all__ = [
    "GENDERS",
    "PLUGIN_NAME",
    "SOCIAL_SITES",
    "DateOfBirthAttr",
    "PersonalSettings",
    "PersonalTab",
    "SocialAccountAttr",
    "plugin",
    "profile_url",
    "settings_of",
    "social_urls",
    "today",
    "validate_social_account",
    "virtual",
]
