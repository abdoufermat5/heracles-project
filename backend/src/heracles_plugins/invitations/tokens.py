"""Registrations and single-use invitation tokens.

An invitation is sent to an e-mail address. Sending creates (or reuses) a
``hrcRegistration`` entry for the address and a hashed single-use token entry
that points to it. The clear token only travels in the e-mailed link.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from heracles.core.containers import ensure_container
from heracles.core.generalized_time import format_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles.schema import names as schema

TOKEN_TYPE_INVITATION = "invitation"  # noqa: S105
INVITATION_TOKENS_RDN = f"ou=invitation,{schema.RDN.TOKENS}"
REGISTRATION_CLASS = "hrcRegistration"
INVITATION_CLASS = "hrcInvitation"
REGISTRATIONS_RDN = "ou=registrations"
INVITATIONS_RDN = "ou=invitations"

STATE_INVITED = "invited"
STATE_REGISTERED = "registered"
STATES = (STATE_INVITED, STATE_REGISTERED)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def tokens_container(directory: DirectoryClient) -> str:
    return dnlib.join(INVITATION_TOKENS_RDN, directory.base_dn)


@dataclass(frozen=True, slots=True)
class InvitationContext:
    """What a valid invitation token stands for."""

    token_dn: str
    registration_dn: str
    email: str
    invitation_dn: str
    form_dn: str


# ------------------------------------------------------------ registrations


def upsert_registration(
    directory: DirectoryClient, container_base: str, email: str, invitation_dn: str, now: datetime
) -> str:
    """Create the registration of ``email`` (state ``invited``) or re-invite it.

    The registration lives in ``ou=registrations`` of the department
    ``container_base``. A previously registered address cannot be invited again.
    Returns the registration DN.
    """
    flt = (
        f"(&(objectClass={REGISTRATION_CLASS})"
        f"(hrcRegistrationEmailAddress={escape_filter_value(email)}))"
    )
    stamp = format_generalized_time(_utc(now)).encode()
    try:
        found = list(
            directory.search(directory.base_dn, flt, Scope.SUBTREE, ["hrcRegistrationState"])
        )
    except NoSuchObjectError:
        found = []
    if found:
        existing = found[0]
        if existing.text("hrcRegistrationState") == STATE_REGISTERED:
            raise ValueError("This address is already registered.")
        directory.modify(
            existing.dn,
            [
                Modification("replace", "hrcRegistrationInvitationDN", [invitation_dn.encode()]),
                Modification("replace", "hrcRegistrationLastChange", [stamp]),
            ],
        )
        return existing.dn
    container = dnlib.join(REGISTRATIONS_RDN, container_base)
    ensure_container(directory, container)
    dn = f"hrcRegistrationEmailAddress={dnlib.escape_rdn_value(email)},{container}"
    directory.add(
        dn,
        {
            "objectClass": [REGISTRATION_CLASS.encode()],
            "hrcRegistrationEmailAddress": [email.encode()],
            "hrcRegistrationState": [STATE_INVITED.encode()],
            "hrcRegistrationLastChange": [stamp],
            "hrcRegistrationInvitationDN": [invitation_dn.encode()],
        },
    )
    return dn


def complete_registration(
    directory: DirectoryClient, context: InvitationContext, user_dn: str, now: datetime
) -> None:
    """Mark the registration as done (links the created user) and burn the token."""
    stamp = format_generalized_time(_utc(now)).encode()
    directory.modify(
        context.registration_dn,
        [
            Modification("replace", "hrcRegistrationState", [STATE_REGISTERED.encode()]),
            Modification("replace", "hrcRegistrationUserDN", [user_dn.encode()]),
            Modification("replace", "hrcRegistrationLastChange", [stamp]),
        ],
    )
    with contextlib.suppress(NoSuchObjectError):
        directory.delete(context.token_dn)


# ------------------------------------------------------------------- tokens


def create_invitation_token(
    directory: DirectoryClient, registration_dn: str, *, now: datetime, valid_days: int
) -> str:
    """Store a hashed single-use token for ``registration_dn``; returns the clear value.

    A previous token of the same registration is replaced.
    """
    container = tokens_container(directory)
    ensure_container(directory, container)
    flt = (
        f"(&(objectClass={schema.OC.TOKEN})({schema.ATTR.TOKEN_TYPE}={TOKEN_TYPE_INVITATION})"
        f"({schema.ATTR.TOKEN_USER_DN}={escape_filter_value(registration_dn)}))"
    )
    try:
        for old in list(directory.search(container, flt, attrs=[schema.ATTR.TOKEN_USER_DN])):
            owner = old.text(schema.ATTR.TOKEN_USER_DN) or ""
            if dnlib.normalize(owner) == dnlib.normalize(registration_dn):
                directory.delete(old.dn)
    except NoSuchObjectError:
        pass
    token = secrets.token_urlsafe(32)
    hashed = hash_token(token)
    expires = int(_utc(now).timestamp()) + valid_days * 86400
    directory.add(
        f"cn={hashed},{container}",
        {
            "objectClass": [schema.OC.TOKEN.encode()],
            "cn": [hashed.encode()],
            schema.ATTR.TOKEN: [hashed.encode()],
            schema.ATTR.TOKEN_TYPE: [TOKEN_TYPE_INVITATION.encode()],
            schema.ATTR.TOKEN_USER_DN: [registration_dn.encode()],
            schema.ATTR.TOKEN_TIMESTAMP: [str(expires).encode()],
        },
    )
    return token


class InvitationUsedError(Exception):
    """The token was consumed by another submission."""


def claim_token(directory: DirectoryClient, context: InvitationContext) -> Entry:
    """Consume the token of ``context`` so that only one submission can use it.

    :func:`resolve_invitation_token` only reads, so two submissions racing with one token
    both pass it. The claim is the deletion of the token entry, which the directory
    performs atomically: one caller deletes it, the others get ``NoSuchObjectError`` and
    :class:`InvitationUsedError`. Returns the removed entry for :func:`release_token`.
    """
    entry = directory.get(context.token_dn)
    if entry is None:
        raise InvitationUsedError(context.token_dn)
    try:
        directory.delete(context.token_dn)
    except NoSuchObjectError:
        raise InvitationUsedError(context.token_dn) from None
    return entry


def release_token(directory: DirectoryClient, claimed: Entry) -> None:
    """Put a claimed token back (the submission failed, the person may try again)."""
    with contextlib.suppress(AlreadyExistsError):
        directory.add(claimed.dn, claimed.attrs)


def _token_entry(directory: DirectoryClient, token: str) -> Entry | None:
    hashed = hash_token(token)
    flt = (
        f"(&(objectClass={schema.OC.TOKEN})({schema.ATTR.TOKEN_TYPE}={TOKEN_TYPE_INVITATION})"
        f"({schema.ATTR.TOKEN}={escape_filter_value(hashed)}))"
    )
    try:
        found = list(directory.search(tokens_container(directory), flt))
    except NoSuchObjectError:
        return None
    return next(
        (
            e
            for e in found
            if hmac.compare_digest((e.text(schema.ATTR.TOKEN) or "").encode(), hashed.encode())
        ),
        None,
    )


def resolve_invitation_token(
    directory: DirectoryClient, token: str, now: datetime
) -> InvitationContext | None:
    """The context of a valid (known, unexpired, not yet registered) token, else ``None``.

    The token is not consumed; :func:`claim_token` does that.
    """
    entry = _token_entry(directory, token)
    if entry is None:
        return None
    try:
        expires = int(entry.text(schema.ATTR.TOKEN_TIMESTAMP) or "0")
    except ValueError:
        return None
    if _utc(now).timestamp() > expires:
        return None
    registration_dn = entry.text(schema.ATTR.TOKEN_USER_DN) or ""
    registration = directory.get(registration_dn) if registration_dn else None
    if registration is None or registration.text("hrcRegistrationState") == STATE_REGISTERED:
        return None
    invitation_dn = registration.text("hrcRegistrationInvitationDN") or ""
    invitation = directory.get(invitation_dn, ["hrcInvitationFormDN"]) if invitation_dn else None
    form_dn = invitation.text("hrcInvitationFormDN") if invitation is not None else None
    if not form_dn:
        return None
    return InvitationContext(
        token_dn=entry.dn,
        registration_dn=registration.dn,
        email=registration.text("hrcRegistrationEmailAddress") or "",
        invitation_dn=invitation_dn,
        form_dn=form_dn,
    )


__all__ = [
    "INVITATION_CLASS",
    "REGISTRATION_CLASS",
    "STATES",
    "STATE_INVITED",
    "STATE_REGISTERED",
    "InvitationContext",
    "InvitationUsedError",
    "claim_token",
    "complete_registration",
    "create_invitation_token",
    "hash_token",
    "release_token",
    "resolve_invitation_token",
    "upsert_registration",
]
