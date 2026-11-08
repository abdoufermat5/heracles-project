from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

import pytest

from heracles import demo
from heracles.cli.main import main
from heracles.ldap.client import DirectoryClient
from heracles.ldap.memory import MemoryDirectory


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


def run(directory: MemoryDirectory, *argv: str) -> int:
    def factory(_args: argparse.Namespace) -> Mapping[str, DirectoryClient]:
        return {"main": directory}

    return main(list(argv), directories=factory)


def test_check_json_and_exit_code(
    directory: MemoryDirectory, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(directory, "check", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in data} >= {"root_object", "super_admin", "default_roles"}


def test_check_text_lists_fixes(
    directory: MemoryDirectory, capsys: pytest.CaptureFixture[str]
) -> None:
    run(directory, "check")
    out = capsys.readouterr().out
    assert "[WARN] default_roles" in out and "fix: heracles fix default_roles" in out


def test_fix_and_create_admin(
    directory: MemoryDirectory, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(directory, "fix", "default_roles") == 0
    assert "fixed" in capsys.readouterr().out
    assert run(directory, "create-admin", "--uid", "root", "--password", "longenough1") == 0
    assert f"uid=root,ou=people,{demo.BASE}" in directory
    assert run(directory, "create-admin", "--uid", "x", "--password", "a") == 2
    assert run(directory, "create-admin", "--uid", "root", "--password", "longenough1") == 1
    assert run(directory, "fix", "super_admin", "--user", "uid=nobody,dc=x") == 1


def test_unknown_directory(directory: MemoryDirectory, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(directory, "check", "--directory", "other") == 2
    assert "unknown directory" in capsys.readouterr().err
