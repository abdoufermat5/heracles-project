"""Unit and integration tests for the Mail plugin."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import heracles_plugins.mail as mail
from heracles.attributes import ValidationError
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.objects.errors import UnknownTypeError
from heracles.schema import legacy

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
ALIAS = f"ou=alias,{BASE}"

MAIL_CLASSES = {
    "gosamailaccount",
    "fdgroupmail",
    "mailaliasdistribution",
    "mailaliasredirection",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    all_classes = {
        *legacy.COMPAT_OBJECT_CLASSES,
        "inetOrgPerson",
        "organizationalPerson",
        "person",
        "groupOfNames",
        "domain",
        "organizationalUnit",
        "gosaMailAccount",
        "fdGroupMail",
        "mailAliasDistribution",
        "mailAliasRedirection",
    }
    d = MemoryDirectory(BASE, object_classes=all_classes)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(GROUPS, {"objectClass": [b"organizationalUnit"], "ou": [b"groups"]})
    d.add(ALIAS, {"objectClass": [b"organizationalUnit"], "ou": [b"alias"]})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        mail.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def new_user(
    service: ObjectService,
    uid: str = "jdoe",
    mail_values: dict[str, Any] | None = None,
    mail_active: bool = True,
) -> str:
    tabs: dict[str, Any] = {
        "main": {"values": {"uid": uid, "givenName": "Jérôme", "sn": "Doe"}},
    }
    if mail_active:
        tabs["mail"] = {"active": True, "values": mail_values or {}}
    return service.create("user", BASE, tabs)


def new_group(
    service: ObjectService,
    cn: str = "devs",
    mail_values: dict[str, Any] | None = None,
    mail_active: bool = True,
    member: str = "",
) -> str:
    tabs: dict[str, Any] = {
        "main": {
            "values": {
                "cn": cn,
                "description": "Dev team",
                "member": [member] if member else [],
            }
        },
    }
    if mail_active:
        tabs["mail"] = {"active": True, "values": mail_values or {}}
    return service.create("group", BASE, tabs)


# -------------------------------------------------------- flags encoding


def test_parse_delivery_mode() -> None:
    flags, unk = mail.parse_delivery_mode("[VL]")
    assert flags == {
        "flag_vacation": True,
        "flag_localonly": True,
        "flag_ownmailbox": False,
    }
    assert unk == ""

    flags, unk = mail.parse_delivery_mode("[]")
    assert flags == {
        "flag_vacation": False,
        "flag_localonly": False,
        "flag_ownmailbox": False,
    }
    assert unk == ""

    flags, unk = mail.parse_delivery_mode(None)
    assert flags == {
        "flag_vacation": False,
        "flag_localonly": False,
        "flag_ownmailbox": False,
    }
    assert unk == ""

    flags, unk = mail.parse_delivery_mode("[VXYZ]")
    assert flags["flag_vacation"] is True
    assert flags["flag_localonly"] is False
    assert flags["flag_ownmailbox"] is False
    assert unk == "XYZ"


def test_format_delivery_mode() -> None:
    assert (
        mail.format_delivery_mode(
            {
                "flag_vacation": True,
                "flag_localonly": True,
                "flag_ownmailbox": False,
            }
        )
        == "[VL]"
    )
    assert (
        mail.format_delivery_mode(
            {
                "flag_vacation": True,
                "flag_localonly": True,
                "flag_ownmailbox": True,
            }
        )
        == "[VLI]"
    )
    assert mail.format_delivery_mode({}) == "[]"

    # Preserves unknown characters from original_mode
    assert (
        mail.format_delivery_mode(
            {"flag_vacation": False, "flag_localonly": True, "flag_ownmailbox": True},
            original_mode="[VXYZ]",
        )
        == "[XYZLI]"
    )

    # Order of original letters preserved
    assert (
        mail.format_delivery_mode(
            {"flag_vacation": True, "flag_localonly": True},
            original_mode="[LV]",
        )
        == "[LV]"
    )


# --------------------------------------------------- timestamp attribute


def test_unix_timestamp_date_attr() -> None:
    attr = mail.UnixTimestampDateAttr("exp", "Expiration")

    d = date(2026, 11, 7)
    raw = attr.to_ldap(d)
    assert raw == [b"1794009600"]
    assert attr.from_ldap(raw) == d
    assert attr.to_ldap(None) == []
    assert attr.from_ldap([]) is None
    assert attr.from_ldap([b"not-a-number"]) is None

    # JSON conversions
    assert attr.from_json("2026-11-07") == d
    assert attr.from_json(1794009600) == d
    assert attr.from_json("1794009600") == d
    assert attr.from_json(None) is None
    assert attr.from_json("") is None

    with pytest.raises(ValidationError):
        attr.from_json("invalid-date")


# ------------------------------------------------------------- ascii fold


def test_fold_ascii() -> None:
    assert mail.fold_ascii("Jérôme") == "jerome"
    assert mail.fold_ascii("Müller") == "muller"
    assert mail.fold_ascii("Élodie") == "elodie"
    assert mail.fold_ascii("Chloé") == "chloe"
    assert mail.fold_ascii("  Lefèvre  ") == "lefevre"


# --------------------------------------------------- plugin registration


def test_plugin_conditional_types(directory: MemoryDirectory) -> None:
    # 1. When alias classes are missing
    reg1 = TypeRegistry()
    register_builtin_types(reg1)
    st1 = reg1.register_plugin(mail.plugin(), {"gosamailaccount"})
    assert st1.enabled
    with pytest.raises(UnknownTypeError):
        reg1.get("mail_alias_distribution")
    with pytest.raises(UnknownTypeError):
        reg1.get("mail_alias_redirection")

    # 2. When alias classes are present
    reg2 = TypeRegistry()
    register_builtin_types(reg2)
    st2 = reg2.register_plugin(
        mail.plugin(),
        {"gosamailaccount", "mailaliasdistribution", "mailaliasredirection"},
    )
    assert st2.enabled
    assert reg2.get("mail_alias_distribution").name == "mail_alias_distribution"
    assert reg2.get("mail_alias_redirection").name == "mail_alias_redirection"

    # 3. When gosaMailAccount is missing
    reg3 = TypeRegistry()
    register_builtin_types(reg3)
    st3 = reg3.register_plugin(mail.plugin(), {"mailaliasdistribution"})
    assert not st3.enabled
    assert "gosaMailAccount" in st3.missing_object_classes

    # 4. Standalone alias_plugin entry point
    reg4 = TypeRegistry()
    register_builtin_types(reg4)
    st4 = reg4.register_plugin(
        mail.alias_plugin(),
        {"mailaliasdistribution", "mailaliasredirection"},
    )
    assert st4.enabled
    assert reg4.get("mail_alias_distribution").name == "mail_alias_distribution"


# -------------------------------------------------------- user mail tab


def test_user_mail_tab_creation_and_load(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(
        service,
        uid="alice",
        mail_values={
            "mail": "alice@example.com",
            "gosaMailServer": "imap.example.com",
            "gosaMailQuota": 500,
            "gosaMailAlternateAddress": ["alice.alias@example.com"],
            "gosaMailForwardingAddress": ["alice.work@example.com"],
            "flag_localonly": True,
            "flag_vacation": True,
            "gosaVacationStart": "2026-11-01",
            "gosaVacationStop": "2026-11-15",
            "gosaVacationMessage": "Out of office",
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("gosaMailAccount")
    assert entry.text("mail") == "alice@example.com"
    assert entry.text("gosaMailServer") == "imap.example.com"
    assert entry.text("gosaMailQuota") == "500"
    assert entry.text("gosaMailDeliveryMode") == "[VL]"
    assert entry.text("gosaVacationStart") == str(
        int(mail.datetime(2026, 11, 1, 0, 0, tzinfo=mail.UTC).timestamp())
    )
    assert entry.text("gosaVacationStop") == str(
        int(mail.datetime(2026, 11, 15, 0, 0, tzinfo=mail.UTC).timestamp())
    )
    assert entry.text("gosaVacationMessage") == "Out of office"

    # Verify loaded state
    state = service.load("user", dn)
    mail_state = state.tabs["mail"]
    assert mail_state.active
    assert mail_state.values["mail"] == "alice@example.com"
    assert mail_state.values["flag_vacation"] is True
    assert mail_state.values["flag_localonly"] is True
    assert mail_state.values["flag_ownmailbox"] is False
    assert mail_state.values["gosaVacationStart"] == date(2026, 11, 1)
    assert mail_state.values["gosaVacationStop"] == date(2026, 11, 15)


def test_user_mail_quota_negative_rejected(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc_info:
        new_user(
            service,
            uid="badquota",
            mail_values={"mail": "bad@example.com", "gosaMailQuota": -10},
        )
    assert "mail.gosaMailQuota" in exc_info.value.fields


def test_user_mail_vacation_stop_before_start_rejected(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc_info:
        new_user(
            service,
            uid="badtimes",
            mail_values={
                "mail": "badtimes@example.com",
                "flag_vacation": True,
                "gosaVacationStart": "2026-11-20",
                "gosaVacationStop": "2026-11-10",
            },
        )
    assert "mail.gosaVacationStop" in exc_info.value.fields


def test_user_mail_vacation_cleared_when_flag_off(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    # 1. Create with vacation on
    dn = new_user(
        service,
        uid="vacationer",
        mail_values={
            "mail": "vac@example.com",
            "flag_vacation": True,
            "gosaVacationStart": "2026-11-01",
            "gosaVacationStop": "2026-11-10",
            "gosaVacationMessage": "I am away",
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("gosaVacationMessage") == "I am away"

    # 2. Turn off vacation
    service.update(
        "user",
        dn,
        {
            "mail": {
                "values": {
                    "flag_vacation": False,
                }
            }
        },
    )
    updated = directory.get(dn)
    assert updated is not None
    assert updated.get("gosaVacationStart") == []
    assert updated.get("gosaVacationStop") == []
    assert updated.get("gosaVacationMessage") == []
    assert updated.text("gosaMailDeliveryMode") == "[]"


def test_user_mail_unknown_delivery_flags_preserved(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_user(
        service,
        uid="specialflags",
        mail_values={"mail": "flags@example.com"},
    )
    # Inject unknown flag X into LDAP directly
    directory.modify(
        dn,
        [Modification("replace", "gosaMailDeliveryMode", [b"[VX]"])],
    )

    # Load and update flag_localonly = True
    service.update(
        "user",
        dn,
        {
            "mail": {
                "values": {
                    "flag_localonly": True,
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    mode = entry.text("gosaMailDeliveryMode") or ""
    # X and V and L should be in mode
    assert "X" in mode
    assert "V" in mode
    assert "L" in mode


# --------------------------------------------------------- template fill


def test_default_domain_helper_template(service: ObjectService, directory: MemoryDirectory) -> None:
    service.registry.settings[mail.PLUGIN_NAME] = mail.MailSettings(
        mail_template="{uid}@heracles.test"
    )
    # Create user with empty mail field in mail tab
    dn = new_user(service, uid="jdoe", mail_values={})
    entry = directory.get(dn)
    assert entry is not None
    assert entry.text("mail") == "jdoe@heracles.test"


def test_default_domain_helper_template_ascii_folded(service: ObjectService) -> None:
    service.registry.settings[mail.PLUGIN_NAME] = mail.MailSettings(
        mail_template="{givenName}.{sn}@example.org"
    )
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "elodie", "givenName": "Élodie", "sn": "Müller"}},
            "mail": {"active": True, "values": {}},
        },
    )
    state = service.load("user", dn)
    assert state.tabs["mail"].values["mail"] == "elodie.muller@example.org"


def test_default_domain_helper_does_not_override_existing(service: ObjectService) -> None:
    service.registry.settings[mail.PLUGIN_NAME] = mail.MailSettings(
        mail_template="{uid}@example.com"
    )
    dn = new_user(service, uid="bob", mail_values={"mail": "custom@other.com"})
    state = service.load("user", dn)
    assert state.tabs["mail"].values["mail"] == "custom@other.com"


# ------------------------------------------------------------- uniqueness


def test_uniqueness_user_vs_user(service: ObjectService) -> None:
    new_user(
        service,
        uid="u1",
        mail_values={
            "mail": "u1@example.com",
            "gosaMailAlternateAddress": ["u1-alt@example.com"],
        },
    )

    # Conflict on primary mail
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, uid="u2", mail_values={"mail": "u1@example.com"})
    assert "mail.mail" in exc.value.fields

    # Conflict on alternate address matching existing primary mail
    with pytest.raises(ObjectValidationError) as exc:
        new_user(
            service,
            uid="u3",
            mail_values={
                "mail": "u3@example.com",
                "gosaMailAlternateAddress": ["u1@example.com"],
            },
        )
    assert "mail.gosaMailAlternateAddress" in exc.value.fields

    # Conflict on primary mail matching existing alternate address
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, uid="u4", mail_values={"mail": "u1-alt@example.com"})
    assert "mail.mail" in exc.value.fields

    # Conflict on alternate address matching existing alternate address
    with pytest.raises(ObjectValidationError) as exc:
        new_user(
            service,
            uid="u5",
            mail_values={
                "mail": "u5@example.com",
                "gosaMailAlternateAddress": ["u1-alt@example.com"],
            },
        )
    assert "mail.gosaMailAlternateAddress" in exc.value.fields


def test_uniqueness_within_same_entry(service: ObjectService) -> None:
    # Alternate cannot be primary
    with pytest.raises(ObjectValidationError) as exc:
        new_user(
            service,
            uid="selfdup",
            mail_values={
                "mail": "same@example.com",
                "gosaMailAlternateAddress": ["same@example.com"],
            },
        )
    assert "mail.gosaMailAlternateAddress" in exc.value.fields

    # Duplicate alternate addresses
    with pytest.raises(ObjectValidationError) as exc:
        new_user(
            service,
            uid="listdup",
            mail_values={
                "mail": "listdup@example.com",
                "gosaMailAlternateAddress": ["dup@example.com", "dup@example.com"],
            },
        )
    assert "mail.gosaMailAlternateAddress" in exc.value.fields


def test_uniqueness_user_vs_group(service: ObjectService) -> None:
    u_dn = new_user(
        service,
        uid="u_group",
        mail_values={"mail": "shared@example.com"},
    )
    assert u_dn

    # Group cannot take user mail
    with pytest.raises(ObjectValidationError) as exc:
        new_group(service, cn="g1", mail_values={"mail": "shared@example.com"}, member=u_dn)
    assert "mail.mail" in exc.value.fields

    # Group can take a unique mail
    g_dn = new_group(
        service,
        cn="g2",
        mail_values={
            "mail": "group2@example.com",
            "gosaMailAlternateAddress": ["group2-alias@example.com"],
        },
        member=u_dn,
    )
    assert g_dn

    # User cannot take group's alternate address
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, uid="u_conflict", mail_values={"mail": "group2-alias@example.com"})
    assert "mail.mail" in exc.value.fields


def test_uniqueness_self_update_allowed(service: ObjectService) -> None:
    dn = new_user(
        service,
        uid="selfupdate",
        mail_values={
            "mail": "self@example.com",
            "gosaMailAlternateAddress": ["self-alt@example.com"],
        },
    )
    # Updating unrelated field or keeping same mail succeeds
    service.update(
        "user",
        dn,
        {
            "mail": {
                "values": {
                    "mail": "self@example.com",
                    "gosaMailServer": "imap.updated.org",
                    "gosaMailAlternateAddress": ["self-alt@example.com"],
                }
            }
        },
    )
    state = service.load("user", dn)
    assert state.tabs["mail"].values["gosaMailServer"] == "imap.updated.org"


# ------------------------------------------------------- group mail tab


def test_group_mail_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    u_dn = new_user(service, uid="gm_user", mail_values={"mail": "gm@example.com"})
    g_dn = new_group(
        service,
        cn="devops",
        mail_values={
            "mail": "devops@example.com",
            "gosaMailServer": "mail.example.com",
            "gosaMailAlternateAddress": ["infra@example.com"],
            "gosaMailForwardingAddress": ["external@cloud.com"],
            "fdGroupMailLocalOnly": True,
        },
        member=u_dn,
    )
    entry = directory.get(g_dn)
    assert entry is not None
    assert entry.has_object_class("fdGroupMail")
    assert entry.text("mail") == "devops@example.com"
    assert entry.text("gosaMailServer") == "mail.example.com"
    assert entry.text("fdGroupMailLocalOnly") == "TRUE"
    assert entry.texts("gosaMailAlternateAddress") == ["infra@example.com"]
    assert entry.texts("gosaMailForwardingAddress") == ["external@cloud.com"]


# ----------------------------------------------------------- alias types


def test_mail_alias_distribution_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    # Create
    dn = service.create(
        "mail_alias_distribution",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "marketing-dist",
                    "description": "Marketing distribution list",
                    "mail": "marketing@example.com",
                    "gosaMailAlternateAddress": ["mktg@example.com"],
                    "gosaMailServer": "relay.example.com",
                    "aliasExpirationDate": "2026-12-31",
                }
            }
        },
    )
    assert dnlib.parent(dn) == ALIAS
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("mailAliasDistribution")
    assert entry.text("cn") == "marketing-dist"
    assert entry.text("mail") == "marketing@example.com"
    assert entry.texts("gosaMailAlternateAddress") == ["mktg@example.com"]
    assert entry.text("aliasExpirationDate") == str(
        int(mail.datetime(2026, 12, 31, 0, 0, tzinfo=mail.UTC).timestamp())
    )

    # Read
    state = service.load("mail_alias_distribution", dn)
    assert state.tabs["main"].values["cn"] == "marketing-dist"
    assert state.tabs["main"].values["aliasExpirationDate"] == date(2026, 12, 31)

    # Update
    service.update(
        "mail_alias_distribution",
        dn,
        {
            "main": {
                "values": {
                    "description": "Updated description",
                    "aliasExpirationDate": "2027-01-15",
                }
            }
        },
    )
    updated = service.load("mail_alias_distribution", dn)
    assert updated.tabs["main"].values["description"] == "Updated description"
    assert updated.tabs["main"].values["aliasExpirationDate"] == date(2027, 1, 15)

    # Delete
    service.delete("mail_alias_distribution", dn)
    assert directory.get(dn) is None


def test_mail_alias_redirection_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    # Forwarding address is required with min_length=1
    with pytest.raises(ObjectValidationError) as exc:
        service.create(
            "mail_alias_redirection",
            BASE,
            {
                "main": {
                    "values": {
                        "cn": "empty-fwd",
                        "mail": "empty@example.com",
                        "gosaMailForwardingAddress": [],
                    }
                }
            },
        )
    assert "main.gosaMailForwardingAddress" in exc.value.fields

    # Create valid redirection
    dn = service.create(
        "mail_alias_redirection",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "leads-redir",
                    "description": "Lead redirection",
                    "mail": "leads@example.com",
                    "gosaMailForwardingAddress": ["target@example.com"],
                    "aliasExpirationDate": "2026-12-31",
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert entry.has_object_class("mailAliasRedirection")
    assert entry.text("cn") == "leads-redir"
    assert entry.text("mail") == "leads@example.com"
    assert entry.texts("gosaMailForwardingAddress") == ["target@example.com"]

    # Delete
    service.delete("mail_alias_redirection", dn)
    assert directory.get(dn) is None


def test_alias_uniqueness_across_types(service: ObjectService) -> None:
    # Create distribution alias
    service.create(
        "mail_alias_distribution",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "dist1",
                    "mail": "dist1@example.com",
                }
            }
        },
    )

    # Redirection alias cannot use distribution alias mail
    with pytest.raises(ObjectValidationError) as exc:
        service.create(
            "mail_alias_redirection",
            BASE,
            {
                "main": {
                    "values": {
                        "cn": "redir1",
                        "mail": "dist1@example.com",
                        "gosaMailForwardingAddress": ["dst@example.com"],
                    }
                }
            },
        )
    assert "main.mail" in exc.value.fields

    # User cannot use distribution alias mail
    with pytest.raises(ObjectValidationError) as exc:
        new_user(service, uid="distuser", mail_values={"mail": "dist1@example.com"})
    assert "mail.mail" in exc.value.fields
