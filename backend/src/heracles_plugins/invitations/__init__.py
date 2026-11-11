"""Invitations plugin: e-mail personal links to public forms.

Types (ACL category ``<type>``, main tab key = class name):

* ``invitation`` (``invitation/invitation``, ``ou=invitations``): the form to
  fill in and the mail to send.
* ``registration`` (``registration/registration``, ``ou=registrations``): one
  entry per invited address, with its state (``invited`` / ``registered``).
* tab ``registration`` on ``user`` (``user/userRegistration``): marks users
  created through a form.

``POST /api/v2/invitations/send`` creates the registrations, single-use tokens and
sends the mails. The public form endpoints live in :mod:`heracles_plugins.public_forms`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from heracles.attributes import (
    DateTimeAttr,
    DepartmentAttr,
    DisplayAttr,
    EmailAttr,
    ObjectRefAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.invitations.router import build_router
from heracles_plugins.invitations.sending import (
    DEFAULT_CONTENT,
    InvitationError,
    SendReport,
    render,
    send_invitation,
)
from heracles_plugins.invitations.tokens import (
    INVITATION_CLASS,
    REGISTRATION_CLASS,
    STATE_INVITED,
    STATE_REGISTERED,
    InvitationContext,
    complete_registration,
    create_invitation_token,
    resolve_invitation_token,
    upsert_registration,
)

PLUGIN_NAME = "invitations"
NAME_RE = r"[^\s,=+<>#;\"\\][^,=+<>#;\"\\]*"


@dataclass(slots=True)
class InvitationsSettings:
    """Settings of the invitations plugin."""

    #: Sender address of the invitation mails (empty: the mailer default).
    from_email: str = ""
    #: Mail body used when an invitation has none; placeholders: {link} {email}
    #: {form_title} {expires}.
    default_email_content: str = DEFAULT_CONTENT
    #: Days a personal link stays valid.
    token_valid_days: int = 7
    #: Public address of the web console used in links (empty: the request address).
    public_base_url: str = ""
    #: Default containers (documentation; the types fix ``rdn`` today).
    invitations_rdn: str = "ou=invitations"
    registrations_rdn: str = "ou=registrations"


def settings_of(ctx: TabContext) -> InvitationsSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, InvitationsSettings) else InvitationsSettings()


class Invitation(ObjectType):
    """An invitation to fill in a public form."""

    name = "invitation"
    acl_category = "invitation"
    label = _("Invitation")
    label_plural = _("Invitations")
    nav = "secondary"
    nav_group = "people"
    icon = "send"
    category = "workflow"
    filter = f"(objectClass={INVITATION_CLASS})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=invitations"
    columns = ("cn", "hrcInvitationEmailSubject")
    search_attrs = ("cn", "hrcInvitationEmailSubject")

    class Main(Tab):
        name = "main"
        acl_key = "invitation"
        label = _("Invitation")
        object_classes = (INVITATION_CLASS,)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=NAME_RE),
            ObjectRefAttr(
                "hrcInvitationFormDN",
                _("Form"),
                ref_type="public_form",
                required=True,
                description=_("The public form the invitees are asked to fill in"),
            ),
            ObjectRefAttr(
                "hrcInvitationAuthor",
                _("Author"),
                ref_type="user",
                readonly=True,
                description=_("User who sent the invitation first"),
            ),
        )
        message = Section(
            _("Mail"),
            StringAttr("hrcInvitationEmailSubject", _("Subject"), required=True),
            TextAttr(
                "hrcInvitationEmailContent",
                _("Content"),
                description=_(
                    "Placeholders: {link} (required) {email} {form_title} {expires}. "
                    "Leave empty to use the default text."
                ),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            content = ctx.values.get("hrcInvitationEmailContent")
            if not content:
                ctx.values["hrcInvitationEmailContent"] = settings_of(ctx).default_email_content
            elif isinstance(content, str) and "{link}" not in content:
                ctx.error("hrcInvitationEmailContent", _("The content must contain {link}."))
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(Invitation.rdn, ctx.base))


class Registration(ObjectType):
    """The registration of an invited address."""

    name = "registration"
    acl_category = "registration"
    label = _("Registration")
    label_plural = _("Registrations")
    nav = "hidden"
    nav_group = "people"
    icon = "clipboard-list"
    category = "workflow"
    creatable = False
    filter = f"(objectClass={REGISTRATION_CLASS})"
    main_attr = "hrcRegistrationEmailAddress"
    name_attr = "hrcRegistrationEmailAddress"
    rdn = "ou=registrations"
    columns = ("hrcRegistrationEmailAddress", "hrcRegistrationState", "hrcRegistrationLastChange")
    search_attrs = ("hrcRegistrationEmailAddress",)

    class Main(Tab):
        name = "main"
        acl_key = "registration"
        label = _("Registration")
        object_classes = (REGISTRATION_CLASS,)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            EmailAttr("hrcRegistrationEmailAddress", _("Email address"), required=True),
            SelectAttr(
                "hrcRegistrationState",
                _("State"),
                options=[(STATE_INVITED, _("Invited")), (STATE_REGISTERED, _("Registered"))],
                default=STATE_INVITED,
            ),
            DateTimeAttr("hrcRegistrationLastChange", _("Last change"), readonly=True),
            ObjectRefAttr(
                "hrcRegistrationInvitationDN",
                _("Invitation"),
                ref_type="invitation",
            ),
            ObjectRefAttr("hrcRegistrationUserDN", _("User"), ref_type="user"),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if not ctx.values.get("hrcRegistrationState"):
                ctx.values["hrcRegistrationState"] = STATE_INVITED
            if ctx.creating or ctx.was_touched("hrcRegistrationState"):
                ctx.values["hrcRegistrationLastChange"] = datetime.now(UTC).replace(microsecond=0)
            if ctx.creating:
                ensure_container(ctx.directory, dnlib.join(Registration.rdn, ctx.base))


def _registration_message(_values: dict[str, object]) -> str:
    return _("This account was created through a registration form.")


class UserRegistrationTab(Tab):
    """Marks a user created through a public registration form."""

    name = "registration"
    acl_key = "userRegistration"
    label = _("Registration")
    description = _("Self-registration status of this account")
    optional = True
    object_classes = ("hrcUserRegistration",)

    info = Section(
        _("Registration"),
        DisplayAttr("msg", _("Information"), compute=_registration_message),
    )


def plugin() -> Plugin:
    """Entry point of the invitations plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(Invitation, Registration),
        tabs=(TabAttachment("user", UserRegistrationTab),),
        settings=InvitationsSettings(),
        api_routers=(build_router,),
    )


__all__ = [
    "Invitation",
    "InvitationContext",
    "InvitationError",
    "InvitationsSettings",
    "Registration",
    "SendReport",
    "UserRegistrationTab",
    "complete_registration",
    "create_invitation_token",
    "plugin",
    "render",
    "resolve_invitation_token",
    "send_invitation",
    "upsert_registration",
]
