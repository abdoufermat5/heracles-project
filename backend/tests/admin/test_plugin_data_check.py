"""Health check: data present for a plugin that is switched off."""

from __future__ import annotations

import pytest

from heracles import demo
from heracles.core import setup_checks as sc
from heracles.ldap.memory import MemoryDirectory

BASE = demo.BASE


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def test_warns_with_the_count_for_a_disabled_plugin(directory: MemoryDirectory) -> None:
    ctx = sc.context_for(directory, disabled_plugins=[("posix", ["posixAccount", "shadowAccount"])])
    assert sc.check_plugin_data(ctx).status == "ok"
    directory.add(
        f"uid=unix,ou=people,{BASE}",
        {
            "objectClass": [b"top", b"inetOrgPerson", b"posixAccount"],
            "uid": [b"unix"],
            "cn": [b"Unix"],
            "sn": [b"U"],
            "uidNumber": [b"4242"],
            "gidNumber": [b"4242"],
            "homeDirectory": [b"/home/unix"],
        },
    )
    result = sc.check_plugin_data(ctx)
    assert result.status == "warning"
    assert "posix (1)" in result.message


def test_ok_without_disabled_plugins(directory: MemoryDirectory) -> None:
    assert sc.check_plugin_data(sc.context_for(directory)).status == "ok"
    ctx = sc.context_for(directory, disabled_plugins=[("gizmo", ["gizmoAccount"])])
    assert sc.check_plugin_data(ctx).status == "ok"


def test_is_part_of_the_report(directory: MemoryDirectory) -> None:
    assert "plugin_data" in sc.CHECK_IDS
    assert {r.id for r in sc.run_checks(sc.context_for(directory))} == set(sc.CHECK_IDS)
