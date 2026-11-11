"""Unit and integration tests for the SpamAssassin plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.spamassassin as spamassassin
import heracles_plugins.systems as systems
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
SERVERS = f"ou=servers,ou=systems,{BASE}"
PEOPLE = f"ou=people,{BASE}"

SPAMASSASSIN_CLASSES = {
    "inetOrgPerson",
    "organizationalPerson",
    "person",
    "ieee802Device",
    "device",
    "hrcServer",
    "hrcSpamAssassinServer",
    "hrcSpamAssassinUser",
    "ipHost",
    "hrcNetworkInterface",
}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE, object_classes=SPAMASSASSIN_CLASSES)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    return d


def make_service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    status_sys = registry.register_plugin(systems.plugin(), schema_classes)
    assert status_sys.enabled
    status_spam = registry.register_plugin(spamassassin.plugin(), schema_classes)
    assert status_spam.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_spamassassin_registration_and_acls(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    s_tab = server_info.tab("spamassassin")
    assert s_tab is not None
    assert s_tab.acl_key == "serviceSpamAssassin"
    assert server_info.acl_object(s_tab) == "server/serviceSpamAssassin"
    assert s_tab.optional is True
    assert s_tab.object_classes == ("hrcSpamAssassinServer",)

    user_info = service.registry.get("user")
    u_tab = user_info.tab("spamassassin")
    assert u_tab is not None
    assert u_tab.acl_key == "spamAssassinAccount"
    assert user_info.acl_object(u_tab) == "user/spamAssassinAccount"
    assert u_tab.optional is True
    assert u_tab.object_classes == ("hrcSpamAssassinUser",)


def test_spamassassin_tabs_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(
        ["inetOrgPerson", "organizationalPerson", "person", "ieee802Device", "device", "hrcServer"]
    )
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(spamassassin.plugin(), schema_classes)

    assert registry.get("server").tab("spamassassin") is None
    assert registry.get("user").tab("spamassassin") is None


def test_server_service_tab_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "spam1"}},
            "spamassassin": {
                "active": True,
                "values": {
                    "hrcSpamAssassinRewriteHeader": "[SPAM]",
                    "hrcSpamAssassinRequiredScore": "4.0",
                    "hrcSpamAssassinTrustedNetworks": "192.168.1.0/24 10.0.0.0/8",
                    "hrcSpamAssassinEnableBayes": True,
                    "hrcSpamAssassinBayesAutolearn": True,
                    "hrcSpamAssassinEnableRblCheck": True,
                    "hrcSpamAssassinEnableRazor": False,
                    "hrcSpamAssassinEnableDcc": False,
                    "hrcSpamAssassinEnablePyzor": True,
                    "hrcSpamAssassinRuleName": "LOCAL_RULE",
                    "hrcSpamAssassinRuleDesc": "Custom local spam rule",
                },
            },
        },
    )
    assert dn == f"cn=spam1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcSpamAssassinServer" in entry.get("objectClass")
    assert entry.text("hrcSpamAssassinRewriteHeader") == "[SPAM]"
    assert entry.text("hrcSpamAssassinRequiredScore") == "4.0"
    assert entry.text("hrcSpamAssassinTrustedNetworks") == "192.168.1.0/24 10.0.0.0/8"
    assert entry.text("hrcSpamAssassinEnableBayes") == "TRUE"
    assert entry.text("hrcSpamAssassinEnablePyzor") == "TRUE"
    assert entry.text("hrcSpamAssassinEnableRazor") == "FALSE"
    assert entry.text("hrcSpamAssassinRuleName") == "LOCAL_RULE"
    assert entry.text("hrcSpamAssassinRuleDesc") == "Custom local spam rule"

    loaded = service.load("server", dn)
    assert loaded.tabs["spamassassin"].active is True
    vals = loaded.tabs["spamassassin"].values
    assert vals["hrcSpamAssassinRewriteHeader"] == "[SPAM]"
    assert vals["hrcSpamAssassinRequiredScore"] == "4.0"
    assert vals["hrcSpamAssassinEnableBayes"] is True
    assert vals["hrcSpamAssassinEnablePyzor"] is True

    # Update
    service.update(
        "server",
        dn,
        {
            "spamassassin": {
                "values": {
                    "hrcSpamAssassinRequiredScore": "5.0",
                    "hrcSpamAssassinEnableRazor": True,
                }
            }
        },
    )
    loaded2 = service.load("server", dn)
    assert loaded2.tabs["spamassassin"].values["hrcSpamAssassinRequiredScore"] == "5.0"
    assert loaded2.tabs["spamassassin"].values["hrcSpamAssassinEnableRazor"] is True

    # Deactivate
    service.update("server", dn, {"spamassassin": {"active": False}})
    entry2 = directory.get(dn)
    assert entry2 is not None
    assert b"hrcSpamAssassinServer" not in entry2.get("objectClass")
    assert entry2.get("hrcSpamAssassinRewriteHeader") == []


def test_user_tab_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "spamassassin": {
                "active": True,
                "values": {
                    "hrcSpamAssassinRules": [
                        {
                            "hrcSpamAssassinRules_directive": "required_score",
                            "hrcSpamAssassinRules_value": "4.5",
                        },
                        {
                            "hrcSpamAssassinRules_directive": "whitelist_from",
                            "hrcSpamAssassinRules_value": "*@trustedcorp.com",
                        },
                        {
                            "hrcSpamAssassinRules_directive": "blacklist_from",
                            "hrcSpamAssassinRules_value": "spammer@evil.org",
                        },
                    ]
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcSpamAssassinUser" in entry.get("objectClass")
    assert entry.texts("hrcSpamAssassinRules") == [
        "required_score 4.5",
        "whitelist_from *@trustedcorp.com",
        "blacklist_from spammer@evil.org",
    ]

    loaded = service.load("user", dn)
    assert loaded.tabs["spamassassin"].active is True
    rules = loaded.tabs["spamassassin"].values["hrcSpamAssassinRules"]
    assert len(rules) == 3
    assert rules[0] == {
        "hrcSpamAssassinRules_directive": "required_score",
        "hrcSpamAssassinRules_value": "4.5",
    }
    assert rules[1] == {
        "hrcSpamAssassinRules_directive": "whitelist_from",
        "hrcSpamAssassinRules_value": "*@trustedcorp.com",
    }

    # Update user rules
    service.update(
        "user",
        dn,
        {
            "spamassassin": {
                "values": {
                    "hrcSpamAssassinRules": [
                        {
                            "hrcSpamAssassinRules_directive": "required_score",
                            "hrcSpamAssassinRules_value": "6.0",
                        }
                    ]
                }
            }
        },
    )
    loaded2 = service.load("user", dn)
    rules2 = loaded2.tabs["spamassassin"].values["hrcSpamAssassinRules"]
    assert len(rules2) == 1
    assert rules2[0]["hrcSpamAssassinRules_value"] == "6.0"

    # Deactivate user tab
    service.update("user", dn, {"spamassassin": {"active": False}})
    entry2 = directory.get(dn)
    assert entry2 is not None
    assert b"hrcSpamAssassinUser" not in entry2.get("objectClass")
    assert entry2.get("hrcSpamAssassinRules") == []


def test_mail_servers_helper_spamassassin(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    assert spamassassin.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "non-mail"}}})
    assert spamassassin.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "spam-srv"}},
            "spamassassin": {"active": True, "values": {"hrcSpamAssassinRewriteHeader": "[SPAM]"}},
        },
    )
    assert spamassassin.mail_servers(directory) == ["spam-srv"]
