"""Tests for Macro plugin: telephony macros type and user macro tab."""

from __future__ import annotations

import pytest

import heracles_plugins.macro as macro
from heracles.ldap.client import Entry
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.macro import MacroSettings

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
SYSTEMS = f"ou=systems,{BASE}"
CONFIGS = f"ou=configs,ou=systems,{BASE}"
ASTERISK = f"ou=asterisk,ou=configs,ou=systems,{BASE}"
MACROS = f"ou=macros,ou=asterisk,ou=configs,ou=systems,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(SYSTEMS, {"objectClass": [b"organizationalUnit"], "ou": [b"systems"]})
    d.add(CONFIGS, {"objectClass": [b"organizationalUnit"], "ou": [b"configs"]})
    d.add(ASTERISK, {"objectClass": [b"organizationalUnit"], "ou": [b"asterisk"]})
    d.add(MACROS, {"objectClass": [b"organizationalUnit"], "ou": [b"macros"]})
    d.set_schema_object_classes(d.schema_object_classes() | {"fdphonemacro"})
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    status = registry.register_plugin(macro.plugin(), classes)
    assert status.enabled
    return ObjectService(directory, registry)


def stored_entry(directory: MemoryDirectory, dn: str) -> Entry:
    entry = directory.get(dn)
    assert entry is not None
    return entry


# ------------------------------------------------------------- schema and ACLs


def test_macro_settings() -> None:
    settings = MacroSettings(
        attribute_class="myClass",
        attribute_description="Telephony macro settings",
        attribute_label="Custom Macro",
    )
    assert settings.attribute_class == "myClass"
    assert settings.attribute_description == "Telephony macro settings"
    assert settings.attribute_label == "Custom Macro"


def test_acl_keys_and_rdn(service: ObjectService) -> None:
    macro_type = service.registry.get("phone_macro")
    assert macro_type.type.rdn == "ou=macros,ou=asterisk,ou=configs,ou=systems"
    assert macro_type.acl_category == "phoneMacro"
    assert macro_type.main_tab.acl_key == "phoneMacro"
    assert macro_type.acl_object(macro_type.main_tab) == "phoneMacro/phoneMacro"

    user_type = service.registry.get("user")
    tab = user_type.tab("macro")
    assert tab is not None
    assert tab.acl_key == "Macro"
    assert user_type.acl_object(tab) == "user/Macro"
    assert tab.optional is False


# ----------------------------------------------------------- phone_macro type


def test_create_and_load_phone_macro(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "phone_macro",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "vm-check",
                    "description": "VoiceMail check macro",
                    "fdMacroAction": "Exten => s,1,VoiceMailMain(${MACRO_EXTEN})",
                }
            }
        },
    )
    assert dn.startswith("cn=vm-check,ou=macros,ou=asterisk,ou=configs,ou=systems")
    entry = stored_entry(directory, dn)
    assert entry.has_object_class("fdPhoneMacro")
    assert entry.text("cn") == "vm-check"
    assert entry.text("description") == "VoiceMail check macro"
    assert entry.text("fdMacroAction") == "Exten => s,1,VoiceMailMain(${MACRO_EXTEN})"

    obj = service.load("phone_macro", dn)
    assert obj.tabs["main"].values["cn"] == "vm-check"
    assert obj.tabs["main"].values["fdMacroAction"] == "Exten => s,1,VoiceMailMain(${MACRO_EXTEN})"


def test_update_phone_macro(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "phone_macro",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "stdexten",
                    "description": "Standard extension",
                    "fdMacroAction": "Exten => s,1,Dial(${ARG1})",
                }
            }
        },
    )
    service.update(
        "phone_macro",
        dn,
        {
            "main": {
                "values": {
                    "description": "Updated standard extension",
                    "fdMacroAction": "Exten => s,1,Dial(${ARG1},20)",
                }
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("description") == "Updated standard extension"
    assert entry.text("fdMacroAction") == "Exten => s,1,Dial(${ARG1},20)"


# ------------------------------------------------------------- user macro tab


def test_user_macro_tab(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "macro_user", "givenName": "Macro", "sn": "User"}},
            "macro": {
                "values": {
                    "phoneMacro": "stdexten",
                    "macroParameter": "SIP/100,20",
                }
            },
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("phoneMacro") == "stdexten"
    assert entry.text("macroParameter") == "SIP/100,20"

    obj = service.load("user", dn)
    assert obj.tabs["macro"].active is True
    assert obj.tabs["macro"].values["phoneMacro"] == "stdexten"
    assert obj.tabs["macro"].values["macroParameter"] == "SIP/100,20"

    service.update(
        "user",
        dn,
        {
            "macro": {
                "values": {
                    "phoneMacro": "vm-check",
                    "macroParameter": "100",
                }
            }
        },
    )
    entry = stored_entry(directory, dn)
    assert entry.text("phoneMacro") == "vm-check"
    assert entry.text("macroParameter") == "100"
