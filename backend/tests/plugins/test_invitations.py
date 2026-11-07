"""Invitations: types, registrations, tokens and sending."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

import heracles_plugins.invitations as inv
import heracles_plugins.public_forms as forms
from heracles.attributes import set_default_password_hasher
from heracles.auth.mail import MemoryMailer
from heracles.auth.passwords import PasswordPolicy
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.invitations import (
    InvitationError,
    complete_registration,
    create_invitation_token,
    resolve_invitation_token,
    send_invitation,
)
from heracles_plugins.invitations.sending import invitation_link, render

BASE = "dc=test"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
CLASSES = ["fdPublicForm", "fdInvitation", "fdRegistration", "fdUserRegistration"]


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(f"ou=people,{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.set_schema_object_classes([*d.schema_object_classes(), *CLASSES])
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> Iterator[ObjectService]:
    set_default_password_hasher(PasswordPolicy().hash_new)
    registry = TypeRegistry()
    register_builtin_types(registry)
    available = {c.lower() for c in directory.schema_object_classes()}
    for plugin in (forms.plugin(), inv.plugin()):
        assert registry.register_plugin(plugin, available).enabled
    yield ObjectService(directory, registry)
    set_default_password_hasher(None)


def new_form(service: ObjectService, cn: str = "join") -> str:
    return service.create(
        "public_form",
        BASE,
        {
            "main": {
                "values": {
                    "cn": cn,
                    "fdPublicFormTitle": "Join us",
                    "fdPublicFormTemplateType": "user",
                    "fdPublicFormPrivate": True,
                }
            }
        },
    )


def new_invitation(service: ObjectService, form_dn: str, **extra: object) -> str:
    return service.create(
        "invitation",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "welcome",
                    "fdInvitationFormDN": form_dn,
                    "fdInvitationEmailSubject": "Welcome",
                    **extra,
                }
            }
        },
    )


def test_types_and_acl_keys(service: ObjectService) -> None:
    registry = service.registry
    for name, acl, container in (
        ("invitation", "invitation/invitation", "ou=invitations"),
        ("registration", "registration/registration", "ou=registrations"),
    ):
        info = registry.get(name)
        assert info.acl_object(info.main_tab) == acl
        assert info.type.rdn == container
    user = registry.get("user")
    tab = user.tab("registration")
    assert tab is not None and user.acl_object(tab) == "user/userRegistration"


def test_invitation_content_defaults_and_needs_a_link(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    form = new_form(service)
    dn = new_invitation(service, form)
    assert dn == f"cn=welcome,ou=invitations,{BASE}"
    content = (directory.get(dn) or pytest.fail()).text("fdInvitationEmailContent") or ""
    assert "{link}" in content
    with pytest.raises(ObjectValidationError) as err:
        service.create(
            "invitation",
            BASE,
            {
                "main": {
                    "values": {
                        "cn": "bad",
                        "fdInvitationFormDN": form,
                        "fdInvitationEmailSubject": "S",
                        "fdInvitationEmailContent": "no link here",
                    }
                }
            },
        )
    assert "main.fdInvitationEmailContent" in err.value.fields
    with pytest.raises(ObjectValidationError):
        new_invitation(service, f"cn=missing,ou=forms,{BASE}")


def test_render_and_link() -> None:
    assert render("Hi {name} {unknown}", {"name": "Al"}) == "Hi Al {unknown}"
    link = invitation_link("https://h.example.com/", "my form", "tok/en")
    assert link == "https://h.example.com/forms/my%20form?token=tok%2Fen"


def test_send_creates_registrations_tokens_and_mails(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    form = new_form(service)
    invitation = new_invitation(
        service, form, fdInvitationEmailContent="Go to {link} before {expires} ({email})"
    )
    mailer = MemoryMailer()
    report = send_invitation(
        directory,
        mailer,
        invitation,
        ["A@Example.com", "a@example.com", "broken", "b@example.com"],
        base_url="https://h.example.com",
        now=NOW,
        author_dn=f"uid=admin,ou=people,{BASE}",
        sender="hr@example.com",
    )
    assert report.sent == ["a@example.com", "b@example.com"]
    assert list(report.failed) == ["broken"]
    assert [m.to for m in mailer.outbox] == report.sent
    assert mailer.outbox[0].sender == "hr@example.com"
    assert "2030-06-22" in mailer.outbox[0].body and "(a@example.com)" in mailer.outbox[0].body
    url = urlparse(next(w for w in mailer.outbox[0].body.split() if w.startswith("https://")))
    assert url.path == "/forms/join"
    token = parse_qs(url.query)["token"][0]

    registration = f"fdRegistrationEmailAddress=a@example.com,ou=registrations,{BASE}"
    entry = directory.get(registration) or pytest.fail()
    assert entry.text("fdRegistrationState") == "invited"
    assert entry.text("fdRegistrationInvitationDN") == invitation
    assert (directory.get(invitation) or pytest.fail()).text("fdInvitationAuthor")

    context = resolve_invitation_token(directory, token, NOW)
    assert context is not None
    assert (context.email, context.form_dn) == ("a@example.com", form)
    assert resolve_invitation_token(directory, token + "x", NOW) is None
    assert resolve_invitation_token(directory, token, NOW + timedelta(days=8)) is None

    # the registration type lists what was created
    listed = service.list("registration")
    assert sorted(r.values["fdRegistrationEmailAddress"] for r in listed.items) == report.sent


def test_resend_replaces_the_token_and_registered_addresses_are_refused(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    invitation = new_invitation(service, new_form(service))
    mailer = MemoryMailer()
    send_invitation(directory, mailer, invitation, ["a@example.com"], base_url="https://h", now=NOW)
    send_invitation(directory, mailer, invitation, ["a@example.com"], base_url="https://h", now=NOW)
    tokens = [parse_qs(urlparse(_link(m.body)).query)["token"][0] for m in mailer.outbox]
    assert resolve_invitation_token(directory, tokens[0], NOW) is None
    context = resolve_invitation_token(directory, tokens[1], NOW)
    assert context is not None

    complete_registration(directory, context, f"uid=a,ou=people,{BASE}", NOW)
    entry = directory.get(context.registration_dn) or pytest.fail()
    assert entry.text("fdRegistrationState") == "registered"
    assert entry.text("fdRegistrationUserDN") == f"uid=a,ou=people,{BASE}"
    assert resolve_invitation_token(directory, tokens[1], NOW) is None
    report = send_invitation(
        directory, mailer, invitation, ["a@example.com"], base_url="https://h", now=NOW
    )
    assert report.sent == [] and "already registered" in report.failed["a@example.com"]


def test_mail_failures_are_reported_per_address(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    class Broken:
        def send(self, to: str, subject: str, body: str, *, sender: str | None = None) -> None:
            raise OSError("down")

    invitation = new_invitation(service, new_form(service))
    report = send_invitation(
        directory, Broken(), invitation, ["a@example.com"], base_url="https://h", now=NOW
    )
    assert report.sent == [] and "OSError" in report.failed["a@example.com"]


def test_send_errors(service: ObjectService, directory: MemoryDirectory) -> None:
    mailer = MemoryMailer()
    with pytest.raises(InvitationError):
        send_invitation(directory, mailer, f"cn=x,{BASE}", ["a@b.co"], base_url="h", now=NOW)
    invitation = new_invitation(service, new_form(service))
    with pytest.raises(InvitationError):
        send_invitation(directory, mailer, invitation, [" "], base_url="h", now=NOW)
    registration = f"cn=r,{BASE}"
    token = create_invitation_token(directory, registration, now=NOW, valid_days=1)
    assert resolve_invitation_token(directory, token, NOW) is None  # no such registration


def _link(body: str) -> str:
    return next(w for w in body.split() if w.startswith("https://"))
