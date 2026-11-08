"""Public forms: type, alterations, definition and submission logic."""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

import heracles_plugins.invitations as inv
import heracles_plugins.public_forms as forms
from heracles.attributes import set_default_password_hasher
from heracles.auth.mail import MemoryMailer
from heracles.auth.passwords import PasswordPolicy, is_locked
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.invitations import resolve_invitation_token, send_invitation
from heracles_plugins.invitations.tokens import InvitationUsedError
from heracles_plugins.public_forms.forms import (
    FormError,
    FormPolicy,
    build_submission,
    describe_form,
    find_form,
    parse_rules,
    submit_form,
    template_tabs,
)

BASE = "dc=test"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
CLASSES = ["fdPublicForm", "fdInvitation", "fdRegistration", "fdUserRegistration"]

FIELDS: list[dict[str, Any]] = [
    {"field": "main.uid", "mandatory": True},
    {"field": "main.givenName", "mandatory": True},
    {"field": "main.sn", "mandatory": True},
    {"field": "main.mail", "imported": True},
    {"field": "main.userPassword", "mandatory": True},
    {"field": "main.description", "readonly": True},
    {"field": "main.employeeType", "hidden": True},
]


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


@pytest.fixture
def template(service: ObjectService) -> str:
    return service.create(
        "user",
        BASE,
        {
            "main": {
                "values": {
                    "uid": "template",
                    "givenName": "T",
                    "sn": "Template",
                    "description": "Visitor account",
                    "employeeType": "guest",
                }
            }
        },
    )


def new_form(
    service: ObjectService,
    template_dn: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    **main: object,
) -> str:
    values: dict[str, object] = {
        "cn": "join",
        "fdPublicFormTitle": "Join us",
        "fdPublicFormTemplateType": "user",
        **main,
    }
    if template_dn:
        values["fdPublicFormTemplateDN"] = template_dn
    return service.create(
        "public_form",
        BASE,
        {
            "main": {"values": values},
            "alteration": {"values": {"fdPublicFormAlteredAttributes": fields or FIELDS}},
        },
    )


def visitor(**extra: object) -> dict[str, object]:
    return {
        "main.uid": "jdoe",
        "main.givenName": "John",
        "main.sn": "Doe",
        "main.userPassword": "s3cretpass1",
        **extra,
    }


def load(service: ObjectService, name: str = "join"):
    form = find_form(service.directory, name)
    assert form is not None
    return form


def test_type_acl_keys_and_container(service: ObjectService) -> None:
    info = service.registry.get("public_form")
    assert info.acl_object(info.main_tab) == "publicForm/publicForm"
    alteration = info.tab("alteration")
    assert alteration is not None
    assert info.acl_object(alteration) == "publicForm/publicFormAlteration"
    assert info.type.rdn == "ou=forms"


def test_rules_roundtrip_through_the_directory(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    dn = new_form(service, template, fdPublicFormCaptcha=True, fdPublicFormPrivate=True)
    assert dn == f"cn=join,ou=forms,{BASE}"
    entry = directory.get(dn) or pytest.fail()
    assert "main.uid|TRUE|||" in entry.texts("fdPublicFormAlteredAttributes")
    form = load(service)
    assert form.captcha and form.private and form.template_dn == template
    keys = {r.key: r for r in form.rules}
    assert keys["main.uid"].mandatory and keys["main.description"].readonly
    assert keys["main.employeeType"].hidden and keys["main.mail"].imported
    assert parse_rules(["bad", "main.x|TRUE|FALSE|TRUE|TRUE"])[0].key == "main.x"
    assert service.load("public_form", dn).tabs["main"].values["publicLink"] == "/forms/join"


def test_form_validation(service: ObjectService, template: str) -> None:
    with pytest.raises(ObjectValidationError) as unknown_type:
        new_form(service, fdPublicFormTemplateType="nothing")
    assert "main.fdPublicFormTemplateType" in unknown_type.value.fields
    with pytest.raises(ObjectValidationError) as bad_template:
        new_form(service, f"cn=x,{BASE}")
    assert "main.fdPublicFormTemplateDN" in bad_template.value.fields
    with pytest.raises(ObjectValidationError) as bad_field:
        new_form(service, fields=[{"field": "main.nope"}])
    assert "alteration.fdPublicFormAlteredAttributes" in bad_field.value.fields
    with pytest.raises(ObjectValidationError):
        new_form(service, fields=[{"field": "main.uid"}, {"field": "main.uid"}])
    with pytest.raises(ObjectValidationError):
        new_form(service, fields=[{"field": "main.base"}])


def test_definition_lists_visible_fields_only(service: ObjectService, template: str) -> None:
    new_form(service, template)
    form = load(service)
    info = service.registry.get("user")
    tabs = template_tabs(service.directory, service.registry, form)
    assert tabs["main"]["values"]["description"] == "Visitor account"
    assert "uid" not in tabs["main"]["values"]  # the main attribute is never copied
    body = describe_form(form, info, tabs, email="invitee@example.com")
    by_key = {f["key"]: f for f in body["fields"]}
    assert list(by_key) == [
        "main.uid",
        "main.givenName",
        "main.sn",
        "main.mail",
        "main.userPassword",
        "main.description",
    ]
    assert by_key["main.uid"]["required"] is True and by_key["main.uid"]["kind"] == "string"
    assert by_key["main.mail"]["value"] == "invitee@example.com"
    assert by_key["main.mail"]["readonly"] is True
    assert by_key["main.description"]["value"] == "Visitor account"
    assert by_key["main.description"]["readonly"] is True
    assert by_key["main.userPassword"]["value"] is None
    assert body["invitee_email"] == "invitee@example.com"
    anonymous = describe_form(form, info, tabs)
    assert {f["key"]: f for f in anonymous["fields"]}["main.mail"]["readonly"] is False


def test_submission_creates_the_object_from_template_and_values(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    new_form(service, template, fdPublicFormDefaultLocked=True)
    dn = submit_form(
        directory,
        service.registry,
        load(service),
        visitor(**{"main.mail": "jdoe@example.com"}),
        context=None,
        now=NOW,
    )
    assert dn == f"uid=jdoe,ou=people,{BASE}"
    entry = directory.get(dn) or pytest.fail()
    assert entry.text("description") == "Visitor account"  # template, read only
    assert entry.text("employeeType") == "guest"  # template, hidden
    assert entry.text("mail") == "jdoe@example.com"
    password = entry.text("userPassword") or ""
    assert is_locked(password) and "s3cretpass1" not in password
    assert entry.has_object_class("fdUserRegistration")


def test_invitation_context_imports_the_address_and_completes_the_registration(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    form_dn = new_form(service, template, fdPublicFormPrivate=True)
    invitation = service.create(
        "invitation",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "welcome",
                    "fdInvitationFormDN": form_dn,
                    "fdInvitationEmailSubject": "Welcome",
                }
            }
        },
    )
    mailer = MemoryMailer()
    send_invitation(
        directory, mailer, invitation, ["new@example.com"], base_url="https://h", now=NOW
    )
    token = mailer.outbox[0].body.split("token=")[1].split()[0]
    context = resolve_invitation_token(directory, token, NOW)
    assert context is not None
    dn = submit_form(
        directory,
        service.registry,
        load(service),
        visitor(),
        context=context,
        now=NOW,
    )
    assert (directory.get(dn) or pytest.fail()).text("mail") == "new@example.com"
    registration = directory.get(context.registration_dn) or pytest.fail()
    assert registration.text("fdRegistrationState") == "registered"
    assert registration.text("fdRegistrationUserDN") == dn
    assert resolve_invitation_token(directory, token, NOW) is None


def _invite(service: ObjectService, directory: MemoryDirectory, template: str) -> tuple[Any, str]:
    form_dn = new_form(service, template, fdPublicFormPrivate=True)
    invitation = service.create(
        "invitation",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "welcome",
                    "fdInvitationFormDN": form_dn,
                    "fdInvitationEmailSubject": "Welcome",
                }
            }
        },
    )
    mailer = MemoryMailer()
    send_invitation(
        directory, mailer, invitation, ["new@example.com"], base_url="https://h", now=NOW
    )
    token = mailer.outbox[0].body.split("token=")[1].split()[0]
    context = resolve_invitation_token(directory, token, NOW)
    assert context is not None
    return context, token


def test_a_token_cannot_be_used_twice(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    """Two submissions that both resolved the token before either finished: one wins."""
    context, _ = _invite(service, directory, template)
    form = load(service)
    first = submit_form(directory, service.registry, form, visitor(), context=context, now=NOW)
    with pytest.raises(InvitationUsedError):
        submit_form(
            directory,
            service.registry,
            form,
            visitor(**{"main.uid": "other"}),
            context=context,
            now=NOW,
        )
    assert directory.get(f"uid=other,ou=people,{BASE}") is None
    assert directory.get(first) is not None


def test_simultaneous_submissions_consume_the_token_once(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    context, _ = _invite(service, directory, template)
    form = load(service)
    start = threading.Barrier(8)
    outcomes: list[str] = []

    def submit(i: int) -> None:
        start.wait()
        try:
            submit_form(
                directory,
                service.registry,
                form,
                visitor(**{"main.uid": f"user{i}"}),
                context=context,
                now=NOW,
            )
            outcomes.append("created")
        except InvitationUsedError:
            outcomes.append("used")

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["created", *["used"] * 7]
    created = [e for e in directory.search(f"ou=people,{BASE}", "(uid=user*)")]
    assert len(created) == 1


def test_a_failed_submission_gives_the_token_back(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    context, token = _invite(service, directory, template)
    form = load(service)
    submit_form(directory, service.registry, form, visitor(), context=None, now=NOW)
    # the account name is taken: the creation fails after the token was claimed
    with pytest.raises(ObjectValidationError):
        submit_form(directory, service.registry, form, visitor(), context=context, now=NOW)
    assert resolve_invitation_token(directory, token, NOW) is not None
    dn = submit_form(
        directory, service.registry, form, visitor(**{"main.uid": "free"}), context=context, now=NOW
    )
    assert directory.get(dn) is not None
    assert resolve_invitation_token(directory, token, NOW) is None


def test_values_outside_the_form_are_refused(service: ObjectService, template: str) -> None:
    new_form(service, template)
    form = load(service)
    info = service.registry.get("user")
    tabs = template_tabs(service.directory, service.registry, form)
    for key in ("main.employeeType", "main.description", "main.telephoneNumber", "nope.x"):
        with pytest.raises(ObjectValidationError) as err:
            build_submission(form, info, tabs, visitor(**{key: "x"}))
        assert key in err.value.fields
    missing = visitor()
    del missing["main.uid"]
    with pytest.raises(ObjectValidationError) as err2:
        build_submission(form, info, tabs, missing)
    assert list(err2.value.fields) == ["main.uid"]


def test_object_validation_still_applies(
    service: ObjectService, directory: MemoryDirectory, template: str
) -> None:
    new_form(service, template)
    with pytest.raises(ObjectValidationError) as err:
        submit_form(
            directory,
            service.registry,
            load(service),
            visitor(**{"main.mail": "not-an-address"}),
            context=None,
            now=NOW,
        )
    assert "main.mail" in err.value.fields
    with pytest.raises(ObjectValidationError) as err2:
        submit_form(
            directory,
            service.registry,
            load(service),
            visitor(**{"main.uid": "a b,c"}),
            context=None,
            now=NOW,
        )
    assert "main.uid" in err2.value.fields
    submit_form(directory, service.registry, load(service), visitor(), context=None, now=NOW)
    with pytest.raises(ObjectValidationError) as twice:
        submit_form(directory, service.registry, load(service), visitor(), context=None, now=NOW)
    assert "main.uid" in twice.value.fields


def test_misconfigured_forms(service: ObjectService, directory: MemoryDirectory) -> None:
    new_form(service)
    form = load(service)
    ghost = _replace(form, type_name="ghost")
    with pytest.raises(FormError):
        submit_form(directory, service.registry, ghost, visitor(), context=None, now=NOW)
    missing_template = _replace(form, template_dn=f"uid=gone,ou=people,{BASE}")
    with pytest.raises(FormError):
        submit_form(directory, service.registry, missing_template, visitor(), context=None, now=NOW)


def test_policy_only_allows_the_planned_writes() -> None:
    policy = FormPolicy("user", f"ou=x,{BASE}", {("main", "uid")})
    assert policy.can_write("dn", "main", "uid")
    assert not policy.can_write("dn", "main", "userPassword")
    assert policy.can_create("user", f"OU=x,{BASE}")
    assert not policy.can_create("group", f"ou=x,{BASE}")
    assert not policy.can_create("user", BASE)
    assert not policy.can_read("dn", "main", "uid") and not policy.can_delete("dn", "user")


def _replace(form: Any, **changes: Any) -> Any:
    return dataclasses.replace(form, **changes)
