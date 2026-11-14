"""Unit and integration tests for the Spam filter plugin."""

from __future__ import annotations

import pytest

import heracles_plugins.spam_filter as spam_filter
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
    "hrcSpamFilterServer",
    "hrcSpamFilterUser",
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
    status_spam = registry.register_plugin(spam_filter.plugin(), schema_classes)
    assert status_spam.enabled
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def test_spam_filter_registration_and_acls(service: ObjectService) -> None:
    server_info = service.registry.get("server")
    s_tab = server_info.tab("spam_filter")
    assert s_tab is not None
    assert s_tab.acl_key == "serviceSpamFilter"
    assert server_info.acl_object(s_tab) == "server/serviceSpamFilter"
    assert s_tab.optional is True
    assert s_tab.object_classes == ("hrcSpamFilterServer",)

    user_info = service.registry.get("user")
    u_tab = user_info.tab("spam_filter")
    assert u_tab is not None
    assert u_tab.acl_key == "spamFilterAccount"
    assert user_info.acl_object(u_tab) == "user/spamFilterAccount"
    assert u_tab.optional is True
    assert u_tab.object_classes == ("hrcSpamFilterUser",)


def test_spam_filter_tabs_dropped_without_schema(directory: MemoryDirectory) -> None:
    directory.set_schema_object_classes(
        ["inetOrgPerson", "organizationalPerson", "person", "ieee802Device", "device", "hrcServer"]
    )
    registry = TypeRegistry()
    register_builtin_types(registry)
    schema_classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(systems.plugin(), schema_classes)
    registry.register_plugin(spam_filter.plugin(), schema_classes)

    assert registry.get("server").tab("spam_filter") is None
    assert registry.get("user").tab("spam_filter") is None


def test_server_service_tab_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "spam1"}},
            "spam_filter": {
                "active": True,
                "values": {
                    "hrcSpamFilterRewriteHeader": "[SPAM]",
                    "hrcSpamFilterRequiredScore": "4.0",
                    "hrcSpamFilterTrustedNetworks": "192.168.1.0/24 10.0.0.0/8",
                    "hrcSpamFilterEnableBayes": True,
                    "hrcSpamFilterBayesAutolearn": True,
                    "hrcSpamFilterEnableRblCheck": True,
                    "hrcSpamFilterEnableDistributedCheck": False,
                    "hrcSpamFilterEnableChecksumCheck": False,
                    "hrcSpamFilterEnableCollaborativeCheck": True,
                    "hrcSpamFilterRuleName": "LOCAL_RULE",
                    "hrcSpamFilterRuleDesc": "Custom local spam rule",
                },
            },
        },
    )
    assert dn == f"cn=spam1,{SERVERS}"
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcSpamFilterServer" in entry.get("objectClass")
    assert entry.text("hrcSpamFilterRewriteHeader") == "[SPAM]"
    assert entry.text("hrcSpamFilterRequiredScore") == "4.0"
    assert entry.text("hrcSpamFilterTrustedNetworks") == "192.168.1.0/24 10.0.0.0/8"
    assert entry.text("hrcSpamFilterEnableBayes") == "TRUE"
    assert entry.text("hrcSpamFilterEnableCollaborativeCheck") == "TRUE"
    assert entry.text("hrcSpamFilterEnableDistributedCheck") == "FALSE"
    assert entry.text("hrcSpamFilterRuleName") == "LOCAL_RULE"
    assert entry.text("hrcSpamFilterRuleDesc") == "Custom local spam rule"

    loaded = service.load("server", dn)
    assert loaded.tabs["spam_filter"].active is True
    vals = loaded.tabs["spam_filter"].values
    assert vals["hrcSpamFilterRewriteHeader"] == "[SPAM]"
    assert vals["hrcSpamFilterRequiredScore"] == "4.0"
    assert vals["hrcSpamFilterEnableBayes"] is True
    assert vals["hrcSpamFilterEnableCollaborativeCheck"] is True

    # Update
    service.update(
        "server",
        dn,
        {
            "spam_filter": {
                "values": {
                    "hrcSpamFilterRequiredScore": "5.0",
                    "hrcSpamFilterEnableDistributedCheck": True,
                }
            }
        },
    )
    loaded2 = service.load("server", dn)
    assert loaded2.tabs["spam_filter"].values["hrcSpamFilterRequiredScore"] == "5.0"
    assert loaded2.tabs["spam_filter"].values["hrcSpamFilterEnableDistributedCheck"] is True

    # Deactivate
    service.update("server", dn, {"spam_filter": {"active": False}})
    entry2 = directory.get(dn)
    assert entry2 is not None
    assert b"hrcSpamFilterServer" not in entry2.get("objectClass")
    assert entry2.get("hrcSpamFilterRewriteHeader") == []


def test_user_tab_crud(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = service.create(
        "user",
        BASE,
        {
            "main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "John"}},
            "spam_filter": {
                "active": True,
                "values": {
                    "hrcSpamFilterRules": [
                        {
                            "hrcSpamFilterRules_directive": "required_score",
                            "hrcSpamFilterRules_value": "4.5",
                        },
                        {
                            "hrcSpamFilterRules_directive": "whitelist_from",
                            "hrcSpamFilterRules_value": "*@trustedcorp.com",
                        },
                        {
                            "hrcSpamFilterRules_directive": "blacklist_from",
                            "hrcSpamFilterRules_value": "spammer@evil.org",
                        },
                    ]
                },
            },
        },
    )
    entry = directory.get(dn)
    assert entry is not None
    assert b"hrcSpamFilterUser" in entry.get("objectClass")
    assert entry.texts("hrcSpamFilterRules") == [
        "required_score 4.5",
        "whitelist_from *@trustedcorp.com",
        "blacklist_from spammer@evil.org",
    ]

    loaded = service.load("user", dn)
    assert loaded.tabs["spam_filter"].active is True
    rules = loaded.tabs["spam_filter"].values["hrcSpamFilterRules"]
    assert len(rules) == 3
    assert rules[0] == {
        "hrcSpamFilterRules_directive": "required_score",
        "hrcSpamFilterRules_value": "4.5",
    }
    assert rules[1] == {
        "hrcSpamFilterRules_directive": "whitelist_from",
        "hrcSpamFilterRules_value": "*@trustedcorp.com",
    }

    # Update user rules
    service.update(
        "user",
        dn,
        {
            "spam_filter": {
                "values": {
                    "hrcSpamFilterRules": [
                        {
                            "hrcSpamFilterRules_directive": "required_score",
                            "hrcSpamFilterRules_value": "6.0",
                        }
                    ]
                }
            }
        },
    )
    loaded2 = service.load("user", dn)
    rules2 = loaded2.tabs["spam_filter"].values["hrcSpamFilterRules"]
    assert len(rules2) == 1
    assert rules2[0]["hrcSpamFilterRules_value"] == "6.0"

    # Deactivate user tab
    service.update("user", dn, {"spam_filter": {"active": False}})
    entry2 = directory.get(dn)
    assert entry2 is not None
    assert b"hrcSpamFilterUser" not in entry2.get("objectClass")
    assert entry2.get("hrcSpamFilterRules") == []


def test_mail_servers_helper_spam_filter(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    assert spam_filter.mail_servers(directory) == []

    service.create("server", BASE, {"main": {"values": {"cn": "non-mail"}}})
    assert spam_filter.mail_servers(directory) == []

    service.create(
        "server",
        BASE,
        {
            "main": {"values": {"cn": "spam-srv"}},
            "spam_filter": {"active": True, "values": {"hrcSpamFilterRewriteHeader": "[SPAM]"}},
        },
    )
    assert spam_filter.mail_servers(directory) == ["spam-srv"]
