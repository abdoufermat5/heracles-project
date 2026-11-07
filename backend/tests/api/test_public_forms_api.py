"""Public form endpoints and the invitation flow, end to end."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import heracles_plugins.invitations as inv
import heracles_plugins.public_forms as forms
from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.attributes import set_default_password_hasher
from heracles.auth.mail import MemoryMailer
from heracles.auth.passwords import PasswordPolicy, is_locked
from heracles.auth.ratelimit import RateLimiter
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.server import create_full_app
from heracles_plugins.public_forms import Captcha, PublicFormsSettings, build_public_router

CLASSES = ["fdPublicForm", "fdInvitation", "fdRegistration", "fdUserRegistration"]
PATH = "/api/v2/public/forms"

FIELDS: list[dict[str, Any]] = [
    {"field": "main.uid", "mandatory": True},
    {"field": "main.givenName", "mandatory": True},
    {"field": "main.sn", "mandatory": True},
    {"field": "main.mail", "imported": True},
    {"field": "main.userPassword", "mandatory": True},
    {"field": "main.description", "hidden": True},
]


def person(**extra: object) -> dict[str, object]:
    return {
        "main.uid": "jdoe",
        "main.givenName": "John",
        "main.sn": "Doe",
        "main.userPassword": "s3cretpass1",
        **extra,
    }


class Clock:
    def __init__(self) -> None:
        self.now = 1_900_000_000.0

    def __call__(self) -> float:
        return self.now


class Env:
    """A bare application serving only the public router."""

    def __init__(self, settings: PublicFormsSettings | None = None) -> None:
        self.directory = MemoryDirectory(BASE)
        d = self.directory
        d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
        d.add(f"ou=people,{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
        d.set_schema_object_classes([*d.schema_object_classes(), *CLASSES])
        self.registry = TypeRegistry()
        register_builtin_types(self.registry)
        available = {c.lower() for c in d.schema_object_classes()}
        for plugin in (forms.plugin(), inv.plugin()):
            assert self.registry.register_plugin(plugin, available).enabled
        self.service = ObjectService(d, self.registry)
        self.clock = Clock()
        self.mailer = MemoryMailer()
        self.captcha = Captcha(b"k" * 32, clock=self.clock)
        app = FastAPI()
        app.include_router(
            build_public_router(
                lambda: d,
                settings or PublicFormsSettings(),
                registry_provider=lambda _request: self.registry,
                clock=self.clock,
                limiter=RateLimiter(free_attempts=3, base_delay=30, clock=self.clock),
                captcha=self.captcha,
            )
        )
        self.client = TestClient(app)

    def form(self, **main: object) -> str:
        values: dict[str, object] = {
            "cn": "join",
            "fdPublicFormTitle": "Join us",
            "fdPublicFormText": "Welcome",
            "fdPublicFormFinalText": "Thank you",
            "fdPublicFormTemplateType": "user",
            "fdPublicFormTemplateDN": self.template(),
            **main,
        }
        return self.service.create(
            "public_form",
            BASE,
            {
                "main": {"values": values},
                "alteration": {"values": {"fdPublicFormAlteredAttributes": FIELDS}},
            },
        )

    def template(self) -> str:
        dn = f"uid=template,ou=people,{BASE}"
        if dn not in self.directory:
            self.service.create(
                "user",
                BASE,
                {
                    "main": {
                        "values": {
                            "uid": "template",
                            "givenName": "T",
                            "sn": "T",
                            "description": "From template",
                        }
                    }
                },
            )
        return dn

    def post(self, body: dict[str, Any], name: str = "join") -> Any:
        return self.client.post(f"{PATH}/{name}", json=body)


@pytest.fixture
def hasher() -> Iterator[None]:
    set_default_password_hasher(PasswordPolicy().hash_new)
    yield
    set_default_password_hasher(None)


@pytest.fixture
def env(hasher: None) -> Env:
    return Env()


def test_definition_of_a_public_form(env: Env) -> None:
    env.form()
    r = env.client.get(f"{PATH}/join")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["title"], body["text"], body["private"], body["captcha"]) == (
        "Join us",
        "Welcome",
        False,
        False,
    )
    assert [f["key"] for f in body["fields"]] == [
        "main.uid",
        "main.givenName",
        "main.sn",
        "main.mail",
        "main.userPassword",
    ]
    assert env.client.get(f"{PATH}/missing").status_code == 404


def test_submission_creates_the_user(env: Env) -> None:
    env.form()
    r = env.post({"values": person(**{"main.mail": "j@example.com"})})
    assert r.status_code == 201, r.text
    assert r.json() == {"status": "ok", "message": "Thank you"}
    entry = env.directory.get(f"uid=jdoe,ou=people,{BASE}") or pytest.fail()
    assert entry.text("description") == "From template"
    assert entry.text("mail") == "j@example.com"
    assert (entry.text("userPassword") or "").startswith("{SSHA}")
    assert not is_locked(entry.text("userPassword") or "")


def test_validation_errors_use_the_api_error_format(env: Env) -> None:
    env.form()
    r = env.post({"values": person(**{"main.telephoneNumber": "1", "main.mail": "bad"})})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation"
    assert set(error["fields"]) == {"main.telephoneNumber"}
    r = env.post({"values": person(**{"main.mail": "bad"})})
    assert set(r.json()["error"]["fields"]) == {"main.mail"}
    assert (
        env.post({"values": {k: v for k, v in person().items() if k != "main.sn"}}).status_code
        == 201
    )


def test_default_locked_accounts(env: Env) -> None:
    env.form(fdPublicFormDefaultLocked=True)
    assert env.post({"values": person()}).status_code == 201
    entry = env.directory.get(f"uid=jdoe,ou=people,{BASE}") or pytest.fail()
    assert is_locked(entry.text("userPassword") or "")


def test_terms_and_captcha(env: Env) -> None:
    env.form(fdPublicFormCaptcha=True, fdPublicFormTosUrl="https://example.com/terms")
    assert env.client.get(f"{PATH}/join").json()["tos_url"] == "https://example.com/terms"
    challenge = env.client.get(f"{PATH}/join/captcha").json()
    a, _plus, b = challenge["question"].split()
    answer = str(int(a) + int(b))

    wrong = env.post(
        {"values": person(), "captcha_token": challenge["token"], "captcha_answer": "0"}
    )
    assert wrong.status_code == 422 and "captcha_answer" in wrong.json()["error"]["fields"]
    no_terms = env.post(
        {"values": person(), "captcha_token": challenge["token"], "captcha_answer": answer}
    )
    assert no_terms.status_code == 422 and "accept_terms" in no_terms.json()["error"]["fields"]
    # the challenge was consumed by the previous attempt
    fresh = env.client.get(f"{PATH}/join/captcha").json()
    a, _plus, b = fresh["question"].split()
    ok = env.post(
        {
            "values": person(),
            "captcha_token": fresh["token"],
            "captcha_answer": str(int(a) + int(b)),
            "accept_terms": True,
        }
    )
    assert ok.status_code == 201, ok.text
    replay = env.post(
        {
            "values": person(**{"main.uid": "other"}),
            "captcha_token": fresh["token"],
            "captcha_answer": str(int(a) + int(b)),
            "accept_terms": True,
        }
    )
    assert replay.status_code == 422
    no_captcha_form = env.client.get(f"{PATH}/other/captcha")
    assert no_captcha_form.status_code == 404


def test_failed_attempts_are_rate_limited(env: Env) -> None:
    env.form()
    bad = {"values": {"main.uid": "x"}}
    assert [env.post(bad).status_code for _ in range(3)] == [422, 422, 422]
    limited = env.post(bad)
    assert limited.status_code == 429 and "retry-after" in limited.headers
    assert limited.json()["error"]["code"] == "rate_limited"
    env.clock.now += 3600
    assert env.post({"values": person()}).status_code == 201


def test_successful_submissions_are_limited_per_hour(hasher: None) -> None:
    env = Env(PublicFormsSettings(submissions_per_hour=2))
    env.form()
    for uid in ("a", "b"):
        assert env.post({"values": person(**{"main.uid": uid})}).status_code == 201
    assert env.post({"values": person(**{"main.uid": "c"})}).status_code == 429
    env.clock.now += 3601
    assert env.post({"values": person(**{"main.uid": "c"})}).status_code == 201


def test_large_bodies_are_refused(hasher: None) -> None:
    env = Env(PublicFormsSettings(max_body_bytes=50))
    env.form()
    assert env.post({"values": person()}).status_code == 413


def test_private_form_needs_an_invitation(env: Env) -> None:
    form_dn = env.form(fdPublicFormPrivate=True)
    assert env.client.get(f"{PATH}/join").status_code == 404
    assert env.client.get(f"{PATH}/join", params={"token": "nope"}).status_code == 404
    assert env.post({"values": person()}).status_code == 404

    invitation = env.service.create(
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
    from datetime import UTC, datetime

    inv.send_invitation(
        env.directory,
        env.mailer,
        invitation,
        ["new@example.com"],
        base_url="https://h",
        now=datetime.fromtimestamp(env.clock.now, UTC),
    )
    token = env.mailer.outbox[0].body.split("token=")[1].split()[0]
    env.clock.now += 3600  # the failed attempts above are forgotten
    r = env.client.get(f"{PATH}/join", params={"token": token})
    assert r.status_code == 200
    mail_field = next(f for f in r.json()["fields"] if f["key"] == "main.mail")
    assert (mail_field["value"], mail_field["readonly"]) == ("new@example.com", True)
    ok = env.post({"values": person(), "token": token})
    assert ok.status_code == 201, ok.text
    assert (env.directory.get(f"uid=jdoe,ou=people,{BASE}") or pytest.fail()).text(
        "mail"
    ) == "new@example.com"
    assert env.post({"values": person(**{"main.uid": "again"}), "token": token}).status_code == 404


def test_private_definition_can_be_shown_when_allowed(hasher: None) -> None:
    env = Env(PublicFormsSettings(allow_private_without_invitations=True))
    env.form(fdPublicFormPrivate=True)
    r = env.client.get(f"{PATH}/join")
    assert r.status_code == 200 and r.json()["invitation_required"] is True
    assert env.post({"values": person()}).status_code == 404


# ------------------------------------------------------------ full application


@pytest.fixture
def full_client(hasher: None) -> Iterator[TestClient]:
    directory = demo.build_demo_directory()
    directory.set_schema_object_classes([*directory.schema_object_classes(), *CLASSES])
    settings = ApiSettings(admin_dns=[])
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str, password: str = "heracles") -> Api:
        r = self.post(
            "/auth/login", {"directory": "main", "username": username, "password": password}
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        return self

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def create(self, type_name: str, tabs: dict[str, Any]) -> str:
        r = self.post(f"/objects/{type_name}", {"base": BASE, "tabs": tabs})
        assert r.status_code == 201, r.text
        return str(r.json()["dn"])


def test_invitation_flow_on_the_full_application(full_client: TestClient) -> None:
    admin = Api(full_client).login("admin")
    template = admin.create(
        "user",
        {"main": {"values": {"uid": "tpl", "givenName": "T", "sn": "T", "description": "Guest"}}},
    )
    form = admin.create(
        "public_form",
        {
            "main": {
                "values": {
                    "cn": "guests",
                    "fdPublicFormTitle": "Guests",
                    "fdPublicFormTemplateType": "user",
                    "fdPublicFormTemplateDN": template,
                    "fdPublicFormPrivate": True,
                }
            },
            "alteration": {"values": {"fdPublicFormAlteredAttributes": FIELDS}},
        },
    )
    invitation = admin.create(
        "invitation",
        {
            "main": {
                "values": {
                    "cn": "guests",
                    "fdInvitationFormDN": form,
                    "fdInvitationEmailSubject": "Hello",
                }
            }
        },
    )

    r = admin.post(
        "/invitations/send",
        {"invitation": invitation, "emails": ["guest@example.com", "oops"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sent"] == ["guest@example.com"] and list(r.json()["failed"]) == ["oops"]
    mailer = cast("MemoryMailer", full_client.app.state.heracles.mailer)  # type: ignore[attr-defined]
    body = mailer.outbox[0].body
    assert "/forms/guests?token=" in body
    token = body.split("token=")[1].split()[0]

    public = full_client.get(f"{PATH}/guests", params={"token": token})
    assert public.status_code == 200, public.text
    assert public.json()["invitee_email"] == "guest@example.com"
    done = full_client.post(
        f"{PATH}/guests", json={"values": person(**{"main.uid": "guest1"}), "token": token}
    )
    assert done.status_code == 201, done.text

    page = admin.client.get("/api/v2/objects/registration", params={"base": BASE, "scope": "sub"})
    assert page.json()["total"] == 1
    assert (
        admin.post(
            "/invitations/send",
            {"invitation": f"cn=ghost,ou=invitations,{BASE}", "emails": ["a@b.co"]},
        ).status_code
        == 404
    )

    # one session per client: sign in as someone else last
    helpdesk = Api(full_client).login("helpdesk")
    denied = helpdesk.post("/invitations/send", {"invitation": invitation, "emails": ["a@b.co"]})
    assert denied.status_code == 403


def test_registry_is_built_from_the_plugins_when_the_app_has_none(env: Env) -> None:
    env.form()
    app = FastAPI()
    app.include_router(build_public_router(lambda: env.directory, PublicFormsSettings()))
    client = TestClient(app)
    assert client.get(f"{PATH}/join").status_code == 200
    r = client.post(f"{PATH}/join", json={"values": person(**{"main.uid": "viaplugins"})})
    assert r.status_code == 201, r.text
