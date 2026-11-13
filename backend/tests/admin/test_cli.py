from __future__ import annotations

import argparse
import getpass
import io
import json
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from heracles import demo
from heracles.cli.main import main
from heracles.ldap.client import DirectoryClient
from heracles.ldap.memory import MemoryDirectory


@pytest.fixture
def directory() -> MemoryDirectory:
    return demo.build_demo_directory()


@pytest.fixture(autouse=True)
def _no_secret_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERACLES_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("HERACLES_DATABASE_URL", raising=False)


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


# -- password sources ---------------------------------------------------------------------------
def test_create_admin_reads_the_password_from_a_file(
    directory: MemoryDirectory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = tmp_path / "pw"
    secret.write_text("longenough1\n", encoding="utf-8")
    assert run(directory, "create-admin", "--uid", "root", "--password-file", str(secret)) == 0
    assert f"uid=root,ou=people,{demo.BASE}" in directory
    assert "warning" not in capsys.readouterr().err


def test_create_admin_reads_the_password_from_stdin(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("longenough1\n"))
    assert run(directory, "create-admin", "--uid", "root", "--password-file", "-") == 0
    assert f"uid=root,ou=people,{demo.BASE}" in directory


def test_create_admin_reads_the_password_from_the_environment(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HERACLES_ADMIN_PASSWORD", "longenough1")
    assert run(directory, "create-admin", "--uid", "root") == 0
    assert f"uid=root,ou=people,{demo.BASE}" in directory
    assert "warning" not in capsys.readouterr().err


def test_create_admin_prompts_when_stdin_is_a_terminal(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    answers = iter(["longenough1", "longenough1"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    assert run(directory, "create-admin", "--uid", "root") == 0
    assert f"uid=root,ou=people,{demo.BASE}" in directory


def test_create_admin_refuses_mismatched_prompts(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    answers = iter(["longenough1", "other"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    assert run(directory, "create-admin", "--uid", "root") == 2
    assert "differ" in capsys.readouterr().err


def test_create_admin_needs_a_password_source_without_a_terminal(
    directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert run(directory, "create-admin", "--uid", "root") == 2
    err = capsys.readouterr().err
    assert "--password-file" in err and "HERACLES_ADMIN_PASSWORD" in err


def test_create_admin_warns_about_a_password_on_the_command_line(
    directory: MemoryDirectory, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(directory, "create-admin", "--uid", "root", "--password", "longenough1") == 0
    err = capsys.readouterr().err
    assert "warning" in err and "--password-file" in err
    assert "longenough1" not in err  # the value itself is never echoed


# -- database URL sources -----------------------------------------------------------------------
def _fake_copy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Record the arguments of the copier instead of reaching PostgreSQL."""
    seen: list[tuple[str, str]] = []

    def copy(path: Path, url: str) -> dict[str, int]:
        seen.append((str(path), url))
        return {"sessions": 0}

    monkeypatch.setattr("heracles.storage.copy.copy_sqlite_to_postgres", copy)
    return seen


def test_migrate_to_postgres_warns_about_a_url_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _fake_copy(monkeypatch)
    url = "postgresql://user:pw@db.example/heracles"
    assert main(["db", "migrate-to-postgres", "--from", str(tmp_path / "h.db"), "--to", url]) == 0
    assert seen == [(str(tmp_path / "h.db"), url)]
    err = capsys.readouterr().err
    assert "warning" in err and "HERACLES_DATABASE_URL" in err


def test_migrate_to_postgres_does_not_warn_without_a_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _fake_copy(monkeypatch)
    url = "postgresql://db.example/heracles"
    assert main(["db", "migrate-to-postgres", "--from", str(tmp_path / "h.db"), "--to", url]) == 0
    assert seen[0][1] == url
    assert "warning" not in capsys.readouterr().err


def test_migrate_to_postgres_reads_the_url_from_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _fake_copy(monkeypatch)
    destination = tmp_path / "url"
    destination.write_text("postgresql://db.example/heracles\n", encoding="utf-8")
    argv = ["db", "migrate-to-postgres", "--from", str(tmp_path / "h.db")]
    assert main([*argv, "--to-file", str(destination)]) == 0
    assert seen[0][1] == "postgresql://db.example/heracles"
    assert "warning" not in capsys.readouterr().err


def test_migrate_to_postgres_reads_the_url_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _fake_copy(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("postgresql://db.example/heracles\n"))
    argv = ["db", "migrate-to-postgres", "--from", str(tmp_path / "h.db"), "--to-file", "-"]
    assert main(argv) == 0
    assert seen[0][1] == "postgresql://db.example/heracles"


def test_migrate_to_postgres_uses_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _fake_copy(monkeypatch)
    monkeypatch.setenv("HERACLES_DATABASE_URL", "postgresql://db.example/heracles")
    assert main(["db", "migrate-to-postgres", "--from", str(tmp_path / "h.db")]) == 0
    assert seen[0][1] == "postgresql://db.example/heracles"


def test_migrate_to_postgres_needs_a_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["db", "migrate-to-postgres", "--from", str(tmp_path / "h.db")]) == 2
    assert "HERACLES_DATABASE_URL" in capsys.readouterr().err
