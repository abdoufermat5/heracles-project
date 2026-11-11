"""Tests for personal plugin: attribute encodings, validation, tab lifecycle, and settings."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import heracles_plugins.personal as personal
from heracles.attributes import DateAttr, ListAttr, ValidationError
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.personal import (
    DateOfBirthAttr,
    PersonalSettings,
    PersonalTab,
    SocialAccountAttr,
    profile_url,
    social_urls,
    validate_social_account,
)

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes(d.schema_object_classes() | {"hrcpersonalinfo"})
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        personal.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def create_user(
    service: ObjectService,
    uid: str = "jdoe",
    personal_active: bool = False,
    personal_values: dict[str, Any] | None = None,
) -> str:
    tabs: dict[str, Any] = {
        "main": {"values": {"uid": uid, "givenName": "John", "sn": "Doe"}},
    }
    if personal_active:
        tabs["personal"] = {"active": True, "values": personal_values or {}}
    return service.create("user", BASE, tabs)


# ------------------------------------------------------------- attribute encodings


def test_date_of_birth_attr_encoding_roundtrip() -> None:
    attr = DateOfBirthAttr("hrcDateOfBirth", "Date of birth")
    dob = date(1990, 5, 15)

    # LDAP text encoding YYYY-MM-DD
    raw = attr.to_ldap(dob)
    assert raw == [b"1990-05-15"]
    assert attr.from_ldap(raw) == dob

    # Missing / empty / unparseable LDAP values
    assert attr.from_ldap([]) is None
    assert attr.from_ldap([b""]) is None
    assert attr.from_ldap([b"not-a-date"]) is None
    assert attr.to_ldap(None) == []

    # JSON encoding
    assert attr.to_json(dob) == "1990-05-15"
    assert attr.to_json(None) is None
    assert attr.from_json("1990-05-15") == dob
    assert attr.from_json(None) is None
    assert attr.from_json("") is None

    with pytest.raises(ValidationError):
        attr.from_json("not-a-date")
    with pytest.raises(ValidationError):
        attr.from_json(12345)


def test_date_of_birth_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    attr = DateOfBirthAttr("hrcDateOfBirth", "Date of birth")
    monkeypatch.setattr(personal, "today", lambda: date(2026, 11, 7))

    # Past date is valid
    assert attr.validate(date(1990, 1, 1)) == []
    assert attr.validate(date(2026, 11, 6)) == []

    # Today is not in the past
    problems_today = attr.validate(date(2026, 11, 7))
    assert len(problems_today) == 1
    assert "past" in problems_today[0]

    # Future date is not in the past
    problems_future = attr.validate(date(2026, 11, 8))
    assert len(problems_future) == 1
    assert "past" in problems_future[0]


def test_contract_dates_generalized_time_encoding() -> None:
    start_attr = DateAttr("hrcContractStartDate", "Contract start date")
    end_attr = DateAttr("hrcContractEndDate", "Contract end date")
    d1 = date(2024, 1, 1)
    d2 = date(2026, 12, 31)

    assert start_attr.to_ldap(d1) == [b"20240101000000Z"]
    assert start_attr.from_ldap([b"20240101000000Z"]) == d1
    assert end_attr.to_ldap(d2) == [b"20261231000000Z"]
    assert end_attr.from_ldap([b"20261231000000Z"]) == d2


def test_social_account_composite_encoding_and_first_colon_split() -> None:
    attr = SocialAccountAttr("socialAccount", "Social account")

    # Regular account without colon in id
    gh = {"site": "github", "id": "octocat"}
    raw_gh = attr.to_ldap(gh)
    assert raw_gh == [b"github:octocat"]
    assert attr.from_ldap(raw_gh) == gh

    # Matrix account with colon in id (e.g. @a:b.org) - splits on first colon only
    mx = {"site": "matrix", "id": "@a:b.org"}
    raw_mx = attr.to_ldap(mx)
    assert raw_mx == [b"matrix:@a:b.org"]
    decoded_mx = attr.from_ldap(raw_mx)
    assert decoded_mx is not None
    assert decoded_mx == mx
    assert decoded_mx["site"] == "matrix"
    assert decoded_mx["id"] == "@a:b.org"

    # Matrix account with multiple colons in id (e.g. with port)
    mx_port = {"site": "matrix", "id": "@user:domain.org:8448"}
    raw_mx_port = attr.to_ldap(mx_port)
    assert raw_mx_port == [b"matrix:@user:domain.org:8448"]
    assert attr.from_ldap(raw_mx_port) == mx_port

    # Diaspora with user@pod
    dia = {"site": "diaspora", "id": "alice@diasp.org"}
    assert attr.to_ldap(dia) == [b"diaspora:alice@diasp.org"]
    assert attr.from_ldap([b"diaspora:alice@diasp.org"]) == dia

    # Empty / none handling
    assert attr.to_ldap(None) == []
    assert attr.from_ldap([]) is None


def test_social_account_list_encoding() -> None:
    list_attr = ListAttr("hrcSocialAccount", "Social accounts", SocialAccountAttr())
    items = [
        {"site": "github", "id": "octocat"},
        {"site": "matrix", "id": "@a:b.org"},
        {"site": "twitter", "id": "jack"},
    ]
    raw = list_attr.to_ldap(items)
    assert raw == [b"github:octocat", b"matrix:@a:b.org", b"twitter:jack"]
    assert list_attr.from_ldap(raw) == items
    assert list_attr.to_json(items) == items
    assert list_attr.from_json(items) == items


# -------------------------------------------------------- social account validation


@pytest.mark.parametrize(
    ("site", "account_id"),
    [
        ("github", "octocat"),
        ("github", "a"),
        ("github", "user-name"),
        ("github", "user-123"),
        ("twitter", "jack"),
        ("twitter", "user_123"),
        ("twitter", "x" * 15),
        ("linkedin", "john-doe"),
        ("linkedin", "johndoe123"),
        ("linkedin", "john_doe"),
        ("linkedin", "john.doe"),
        ("matrix", "@user:server"),
        ("matrix", "@a:b.org"),
        ("matrix", "@user:domain.org:8448"),
        ("diaspora", "user@pod"),
        ("diaspora", "alice@diasp.org"),
        ("facebook", "zuck"),
        ("googlescholar", "uV_x4Q8AAAAJ"),
    ],
)
def test_validate_social_account_valid(site: str, account_id: str) -> None:
    assert validate_social_account(site, account_id) is None


@pytest.mark.parametrize(
    ("site", "account_id"),
    [
        ("github", "-leading"),
        ("github", "trailing-"),
        ("github", "double--dash"),
        ("github", "has space"),
        ("github", "has_underscore"),
        ("github", "has.dot"),
        ("github", "a" * 40),
        ("twitter", "a" * 16),
        ("twitter", "user-name"),
        ("twitter", "user name"),
        ("twitter", "user@name"),
        ("linkedin", "has:colon"),
        ("linkedin", "has space"),
        ("matrix", "user:server"),  # missing leading @
        ("matrix", "@user"),  # missing :server
        ("matrix", "@user:"),  # empty server
        ("matrix", "@user:server with space"),
        ("diaspora", "user"),  # missing @pod
        ("diaspora", "@pod"),  # missing user
        ("diaspora", "user@"),  # empty pod
        ("facebook", "has:colon"),
        ("facebook", ""),
        ("googlescholar", "has:colon"),
        ("googlescholar", ""),
    ],
)
def test_validate_social_account_invalid(site: str, account_id: str) -> None:
    problem = validate_social_account(site, account_id)
    assert problem is not None


def test_social_account_attr_validation() -> None:
    attr = SocialAccountAttr()

    # Valid matrix with colon
    assert attr.validate({"site": "matrix", "id": "@a:b.org"}) == []

    # Invalid matrix syntax
    err_mx = attr.validate({"site": "matrix", "id": "invalid"})
    assert any("Matrix" in e for e in err_mx)

    # Colon in non-matrix site is refused
    err_fb = attr.validate({"site": "facebook", "id": "foo:bar"})
    assert any("must not contain ':'" in e for e in err_fb)

    # Empty identifier
    err_empty = attr.validate({"site": "github", "id": ""})
    assert any("required" in e.lower() for e in err_empty)


# ------------------------------------------------------- profile URLs & display attr


def test_profile_url_generation() -> None:
    assert profile_url("github", "octocat") == "https://github.com/octocat"
    assert profile_url("twitter", "jack") == "https://twitter.com/jack"
    assert profile_url("twitter", "@jack") == "https://twitter.com/jack"
    assert profile_url("linkedin", "john-doe") == "https://www.linkedin.com/in/john-doe"
    assert profile_url("facebook", "zuck") == "https://www.facebook.com/zuck"
    assert profile_url("googlescholar", "123") == "https://scholar.google.com/citations?user=123"
    assert profile_url("matrix", "@a:b.org") == "https://matrix.to/#/@a:b.org"
    assert profile_url("diaspora", "user@pod.org") == "https://pod.org/u/user"
    assert profile_url("unknown", "xyz") is None


def test_social_urls_formatter() -> None:
    values: dict[str, Any] = {
        "hrcSocialAccount": [
            {"site": "github", "id": "octocat"},
            {"site": "matrix", "id": "@a:b.org"},
        ]
    }
    expected = "https://github.com/octocat\nhttps://matrix.to/#/@a:b.org"
    assert social_urls(values) == expected

    assert social_urls({}) is None
    assert social_urls({"hrcSocialAccount": []}) is None


# ------------------------------------------------------------------ settings


def test_personal_settings_defaults() -> None:
    settings = PersonalSettings()
    assert settings.private_mail_for_password_recovery is False

    plugin = personal.plugin()
    assert isinstance(plugin.settings, PersonalSettings)
    assert plugin.settings.private_mail_for_password_recovery is False


# ---------------------------------------------------- service-level tab lifecycle


def test_plugin_registration(directory: MemoryDirectory) -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        personal.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    user_info = registry.get("user")
    assert user_info.tab("personal") is not None
    assert user_info.acl_object(PersonalTab) == "user/personalInfo"


def test_plugin_disabled_when_missing_object_class() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(personal.plugin(), {"inetorgperson"})
    assert not status.enabled
    assert status.missing_object_classes == ["hrcPersonalInfo"]


def test_create_user_with_personal_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(
        service,
        uid="alex",
        personal_active=True,
        personal_values={
            "personalTitle": "Dr.",
            "hrcNickName": "Lex",
            "hrcBadge": "BADGE-42",
            "hrcDateOfBirth": "1992-06-18",
            "hrcGender": "M",
            "co": "France",
            "hrcContractStartDate": "2024-01-01",
            "hrcContractEndDate": "2026-12-31",
            "hrcPhotoVisible": True,
            "hrcPrivateMail": ["alex@personal.example"],
            "hrcSocialAccount": [
                {"site": "github", "id": "octocat"},
                {"site": "matrix", "id": "@a:b.org"},
            ],
        },
    )

    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("hrcPersonalInfo")
    assert entry.text("personalTitle") == "Dr."
    assert entry.text("hrcNickName") == "Lex"
    assert entry.text("hrcBadge") == "BADGE-42"
    assert entry.text("hrcDateOfBirth") == "1992-06-18"  # text YYYY-MM-DD
    assert entry.text("hrcGender") == "M"
    assert entry.text("co") == "France"
    assert entry.text("hrcContractStartDate") == "20240101000000Z"  # GeneralizedTime
    assert entry.text("hrcContractEndDate") == "20261231000000Z"  # GeneralizedTime
    assert entry.text("hrcPhotoVisible") == "TRUE"
    assert entry.texts("hrcPrivateMail") == ["alex@personal.example"]
    assert entry.texts("hrcSocialAccount") == ["github:octocat", "matrix:@a:b.org"]

    # Virtual display attribute is NOT stored in directory
    assert not entry.get("socialUrls")

    # When loaded back, virtual attribute is computed
    state = service.load("user", dn)
    assert state.tabs["personal"].active is True
    assert state.tabs["personal"].values["personalTitle"] == "Dr."
    assert state.tabs["personal"].values["hrcDateOfBirth"] == date(1992, 6, 18)
    assert (
        state.tabs["personal"].values["socialUrls"]
        == "https://github.com/octocat\nhttps://matrix.to/#/@a:b.org"
    )


def test_default_photo_visible_is_true(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = create_user(service, uid="photo_user", personal_active=True, personal_values={})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("hrcPersonalInfo")
    assert entry.text("hrcPhotoVisible") == "TRUE"


def test_tab_activation_and_deactivation(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    # 1. Create user with only main tab
    dn = create_user(service, uid="bob")
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("hrcPersonalInfo")

    # 2. Activate personal tab
    service.update(
        "user",
        dn,
        {
            "personal": {
                "active": True,
                "values": {
                    "personalTitle": "Prof.",
                    "hrcNickName": "Bobby",
                    "hrcGender": "M",
                    "hrcPhotoVisible": False,
                },
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("hrcPersonalInfo")
    assert entry.text("personalTitle") == "Prof."
    assert entry.text("hrcNickName") == "Bobby"
    assert entry.text("hrcPhotoVisible") == "FALSE"

    # 3. Deactivate personal tab
    service.update("user", dn, {"personal": {"active": False}})
    entry = directory.get(dn)
    assert entry is not None
    assert not entry.has_object_class("hrcPersonalInfo")
    assert entry.text("personalTitle") is None
    assert entry.text("hrcNickName") is None
    assert entry.text("hrcPhotoVisible") is None


def test_contract_dates_validation_end_before_start(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            uid="bad_dates",
            personal_active=True,
            personal_values={
                "hrcContractStartDate": "2026-01-01",
                "hrcContractEndDate": "2025-01-01",
            },
        )
    assert "personal.hrcContractEndDate" in exc.value.fields


def test_contract_dates_validation_end_equal_start(service: ObjectService) -> None:
    dn = create_user(
        service,
        uid="same_dates",
        personal_active=True,
        personal_values={
            "hrcContractStartDate": "2025-06-01",
            "hrcContractEndDate": "2025-06-01",
        },
    )
    assert dn is not None


def test_date_of_birth_must_be_in_past(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            uid="future_born",
            personal_active=True,
            personal_values={"hrcDateOfBirth": "2099-01-01"},
        )
    assert "personal.hrcDateOfBirth" in exc.value.fields


def test_private_mail_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            uid="bad_mail",
            personal_active=True,
            personal_values={"hrcPrivateMail": ["not-an-email"]},
        )
    assert "personal.hrcPrivateMail" in exc.value.fields


def test_social_account_matrix_validation_error(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_user(
            service,
            uid="bad_matrix",
            personal_active=True,
            personal_values={"hrcSocialAccount": [{"site": "matrix", "id": "not_an_mxid"}]},
        )
    assert "personal.hrcSocialAccount" in exc.value.fields
