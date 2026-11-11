"""Send an invitation: one registration, one token and one e-mail per address."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote

from heracles.auth.mail import Mailer
from heracles.ldap.client import DirectoryClient, Modification
from heracles.objects.service import department_of
from heracles_plugins.invitations.tokens import (
    INVITATION_CLASS,
    INVITATIONS_RDN,
    create_invitation_token,
    upsert_registration,
)

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MAX_RECIPIENTS = 500
#: Frontend route of the public form page (the token is passed as ``token``).
FORM_PATH = "/forms/{name}"

DEFAULT_CONTENT = (
    "Hello,\n\n"
    'You are invited to fill in the form "{form_title}".\n'
    "Please follow this personal link:\n\n"
    "{link}\n\n"
    "The link can be used once and expires on {expires}.\n"
)


class InvitationError(Exception):
    """The invitation cannot be sent (unknown invitation or form, bad request)."""


@dataclass(slots=True)
class SendReport:
    """Outcome of a sending."""

    sent: list[str] = field(default_factory=lambda: [])
    failed: dict[str, str] = field(default_factory=lambda: {})


def render(template: str, values: dict[str, str]) -> str:
    """Replace ``{name}`` placeholders; unknown ones are kept as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)


def invitation_link(base_url: str, form_name: str, token: str) -> str:
    path = FORM_PATH.format(name=quote(form_name, safe=""))
    return f"{base_url.rstrip('/')}{path}?token={quote(token, safe='')}"


def send_invitation(
    directory: DirectoryClient,
    mailer: Mailer,
    invitation_dn: str,
    emails: list[str],
    *,
    base_url: str,
    now: datetime,
    author_dn: str | None = None,
    sender: str | None = None,
    valid_days: int = 7,
) -> SendReport:
    """Invite every address of ``emails`` to the form of the invitation.

    Addresses that are invalid, already registered or whose mail could not be sent
    are reported in :attr:`SendReport.failed`; the others get a fresh personal
    link. ``author_dn`` is recorded on the invitation the first time.
    """
    invitation = directory.get(invitation_dn)
    if invitation is None or not invitation.has_object_class(INVITATION_CLASS):
        raise InvitationError("Unknown invitation.")
    form_dn = invitation.text("hrcInvitationFormDN") or ""
    form = directory.get(form_dn) if form_dn else None
    if form is None:
        raise InvitationError("The form of this invitation does not exist.")
    wanted = list(dict.fromkeys(e.strip().lower() for e in emails if e.strip()))
    if not wanted:
        raise InvitationError("No address given.")
    if len(wanted) > MAX_RECIPIENTS:
        raise InvitationError(f"At most {MAX_RECIPIENTS} addresses at a time.")
    if author_dn and not invitation.text("hrcInvitationAuthor"):
        directory.modify(
            invitation.dn, [Modification("replace", "hrcInvitationAuthor", [author_dn.encode()])]
        )
    form_name = form.text("cn") or ""
    form_title = form.text("hrcPublicFormTitle") or form_name
    subject = invitation.text("hrcInvitationEmailSubject") or form_title
    content = invitation.text("hrcInvitationEmailContent") or DEFAULT_CONTENT
    container_base = department_of(invitation.dn, INVITATIONS_RDN)
    report = SendReport()
    expires = (now.date() + timedelta(days=valid_days)).isoformat()
    for email in wanted:
        if EMAIL_RE.fullmatch(email) is None:
            report.failed[email] = "Invalid email address."
            continue
        try:
            registration = upsert_registration(directory, container_base, email, invitation.dn, now)
        except ValueError as exc:
            report.failed[email] = str(exc)
            continue
        token = create_invitation_token(directory, registration, now=now, valid_days=valid_days)
        body = render(
            content,
            {
                "link": invitation_link(base_url, form_name, token),
                "email": email,
                "form_title": form_title,
                "expires": expires,
            },
        )
        try:
            mailer.send(email, subject, body, sender=sender)
        except Exception as exc:  # any transport failure is reported per address
            report.failed[email] = f"Could not send the mail: {type(exc).__name__}"
            continue
        report.sent.append(email)
    return report


__all__ = [
    "DEFAULT_CONTENT",
    "FORM_PATH",
    "MAX_RECIPIENTS",
    "InvitationError",
    "SendReport",
    "invitation_link",
    "render",
    "send_invitation",
]
