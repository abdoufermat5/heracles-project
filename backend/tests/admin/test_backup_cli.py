"""``heracles backup`` / ``heracles restore``: archive format, refusals, directory export."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from heracles import __version__, demo
from heracles.cli.backup import blank_secrets
from heracles.cli.main import main
from heracles.ldap.client import DirectoryClient, Scope
from heracles.ldap.memory import MemoryDirectory
from heracles.objects.activation import PluginOverrideStore
from heracles.storage import Database
from heracles.storage.copy import component_migrations
from tests.storage import test_dump
from tests.storage.seed import check, seed
from tests.storage.test_dump import BACKENDS, NewTarget

BASE = demo.BASE

#: The throwaway-database fixture of the storage tests (SQLite, and PostgreSQL when configured).
new_target = test_dump.new_target


def write_config(path: Path, target: str | Path, **extra: Any) -> Path:
    database = {"url": target} if str(target).startswith("postgresql://") else {"path": str(target)}
    document: dict[str, Any] = {
        "directories": [
            {
                "id": "main",
                "uri": "ldap://localhost:1",
                "bind_dn": f"cn=admin,{BASE}",
                "bind_password": "s3cret-bind",
                "base_dn": BASE,
            }
        ],
        "api": {"database": database},
        **extra,
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERACLES_DATABASE_URL", raising=False)
    monkeypatch.delenv("HERACLES_CONFIG", raising=False)


def run(*argv: str, directory: DirectoryClient | None = None) -> int:
    def factory(_args: argparse.Namespace) -> Mapping[str, DirectoryClient]:
        return {"main": directory} if directory is not None else {}

    return main(list(argv), directories=factory)


def members(archive: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(archive) as tar:
        for m in tar.getmembers():
            f = tar.extractfile(m)
            assert f is not None
            out[m.name] = f.read()
    return out


def write_members(archive: Path, files: Mapping[str, bytes]) -> None:
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def tamper(
    source: Path, dest: Path, edit: Callable[[dict[str, bytes], dict[str, Any]], None]
) -> Path:
    """A copy of the archive after ``edit(files, manifest)``; the manifest is written back."""
    files = members(source)
    manifest = json.loads(files["manifest.json"])
    edit(files, manifest)
    files["manifest.json"] = json.dumps(manifest).encode()
    write_members(dest, files)
    return dest


def refresh_hash(files: dict[str, bytes], manifest: dict[str, Any], name: str) -> None:
    for entry in manifest["files"]:
        if entry["path"] == name:
            entry["sha256"] = hashlib.sha256(files[name]).hexdigest()
            entry["size"] = len(files[name])


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """An archive of a seeded SQLite database."""
    db = Database(tmp_path / "src.db")
    seed(db)
    db.close()
    config = write_config(tmp_path / "src.yaml", tmp_path / "src.db")
    out = tmp_path / "a.tar.gz"
    assert run("backup", "--config", str(config), "-o", str(out)) == 0
    return out


@pytest.mark.parametrize("target", BACKENDS)
@pytest.mark.parametrize("source", BACKENDS)
def test_backup_then_restore_into_a_new_database(
    source: str,
    target: str,
    new_target: NewTarget,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_target = new_target(source)
    db = Database(source_target)
    session_id = seed(db)
    db.close()
    config = write_config(tmp_path / "src.yaml", source_target)
    out = tmp_path / "backup.tar.gz"
    assert run("backup", "--config", str(config), "-o", str(out)) == 0
    assert "warning" in capsys.readouterr().err  # the secrets are in it

    dest_target = new_target(target)
    dest_config = write_config(tmp_path / "dest.yaml", dest_target)
    assert run("restore", str(out), "--config", str(dest_config)) == 0
    assert "everyone signs in again" in capsys.readouterr().out
    dest = Database(dest_target)
    try:
        check(dest, session_id)
    finally:
        dest.close()


def test_manifest_describes_the_archive(archive: Path) -> None:
    assert archive.stat().st_mode & 0o777 == 0o600
    files = members(archive)
    manifest = json.loads(files["manifest.json"])
    assert manifest["format"] == 1 and manifest["heracles_version"] == __version__
    assert manifest["database"]["dialect"] == "sqlite"
    known = component_migrations()
    assert manifest["database"]["components"]["second_factor"] == len(known["second_factor"])
    assert manifest["database"]["tables"]["task_runs"] == 2
    assert manifest["directory"] is None and manifest["config"]["secrets_excluded"] is False
    listed = {e["path"]: e for e in manifest["files"]}
    assert set(files) == set(listed) | {"manifest.json"}
    for name, entry in listed.items():
        assert hashlib.sha256(files[name]).hexdigest() == entry["sha256"]
        assert len(files[name]) == entry["size"]
    assert "config/src.yaml" in listed and "database/api_tokens.jsonl" in listed
    assert "database/sessions.jsonl" not in listed


def test_backup_without_a_database_or_a_config_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "a.tar.gz"
    assert run("backup", "--config", str(tmp_path / "missing.yaml"), "-o", str(out)) == 1
    config = write_config(tmp_path / "c.yaml", tmp_path / "none.db")
    assert run("backup", "--config", str(config), "-o", str(out)) == 1
    assert "nothing to back up" in capsys.readouterr().err
    assert not out.exists()
    assert run("backup", "-o", str(out)) == 1
    assert "HERACLES_CONFIG" in capsys.readouterr().err


# --- refusals --------------------------------------------------------------------------------
def restore_into(tmp_path: Path, archive: Path, *extra: str) -> tuple[int, Path]:
    target = tmp_path / "dest.db"
    config = write_config(tmp_path / "dest.yaml", target)
    return run("restore", str(archive), "--config", str(config), *extra), target


def test_a_damaged_file_is_refused_and_nothing_is_loaded(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def edit(files: dict[str, bytes], _manifest: dict[str, Any]) -> None:
        files["database/api_tokens.jsonl"] += b" "

    bad = tamper(archive, tmp_path / "bad.tar.gz", edit)
    code, target = restore_into(tmp_path, bad)
    assert code == 1 and "checksum" in capsys.readouterr().err
    assert not target.exists()


def test_files_added_or_missing_are_refused(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def add(files: dict[str, bytes], _manifest: dict[str, Any]) -> None:
        files["database/extra.jsonl"] = b"{}\n"

    code, _ = restore_into(tmp_path, tamper(archive, tmp_path / "x.tar.gz", add))
    assert code == 1 and "does not list" in capsys.readouterr().err

    def drop(files: dict[str, bytes], _manifest: dict[str, Any]) -> None:
        del files["database/api_tokens.jsonl"]

    code, _ = restore_into(tmp_path, tamper(archive, tmp_path / "y.tar.gz", drop))
    assert code == 1 and "lacks database/api_tokens.jsonl" in capsys.readouterr().err


def test_unsafe_member_names_are_refused(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = members(archive)
    files["../evil"] = b"x"
    bad = tmp_path / "bad.tar.gz"
    write_members(bad, files)
    code, _ = restore_into(tmp_path, bad)
    assert code == 1 and "unsafe" in capsys.readouterr().err
    assert not (tmp_path.parent / "evil").exists()


def test_not_an_archive_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not a tar file")
    code, _ = restore_into(tmp_path, junk)
    assert code == 1 and "cannot read the archive" in capsys.readouterr().err
    empty = tmp_path / "empty.tar.gz"
    write_members(empty, {"readme": b"x"})
    code, _ = restore_into(tmp_path, empty)
    assert code == 1 and "manifest.json is missing" in capsys.readouterr().err


def test_a_newer_manifest_format_is_refused(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def edit(_files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        manifest["format"] = 2

    code, target = restore_into(tmp_path, tamper(archive, tmp_path / "new.tar.gz", edit))
    assert code == 1 and "format version 2" in capsys.readouterr().err
    assert not target.exists()


def test_newer_component_migrations_are_refused(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def edit(_files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        manifest["database"]["components"]["access_reviews"] += 1

    code, target = restore_into(tmp_path, tamper(archive, tmp_path / "new.tar.gz", edit))
    assert code == 1 and "'access_reviews'" in capsys.readouterr().err
    assert not target.exists()


def test_a_database_with_data_is_refused_unless_forced(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "dest.db"
    existing = Database(target)
    PluginOverrideStore(existing).set("sudo", True)
    existing.close()
    config = write_config(tmp_path / "dest.yaml", target)

    assert run("restore", str(archive), "--config", str(config)) == 1
    assert "--force" in capsys.readouterr().err
    assert run("restore", str(archive), "--config", str(config), "--force") == 0
    db = Database(target)
    try:
        assert PluginOverrideStore(db).load() == {"sudo": False, "ssh": True}
    finally:
        db.close()


def test_a_bad_row_rolls_the_whole_restore_back(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def edit(files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        files["database/task_runs.jsonl"] += b'{"id": 7}\n'
        refresh_hash(files, manifest, "database/task_runs.jsonl")

    code, target = restore_into(tmp_path, tamper(archive, tmp_path / "bad.tar.gz", edit))
    assert code == 1 and "error" in capsys.readouterr().err
    db = Database(target)
    try:
        with db.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM plugin_overrides").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM second_factor_totp").fetchone()[0] == 0
    finally:
        db.close()


def test_ldif_restore_needs_an_archive_made_with_ldif(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, target = restore_into(tmp_path, archive, "--ldif")
    assert code == 1 and "no directory export" in capsys.readouterr().err
    assert not target.exists()


# --- configuration secrets -------------------------------------------------------------------
def test_exclude_secrets_blanks_the_configuration_in_the_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = Database(tmp_path / "src.db")
    db.close()
    config = write_config(
        tmp_path / "src.yaml",
        tmp_path / "src.db",
        mail={"host": "smtp.example.org", "username": "heracles", "password": "mail-pw"},
    )
    out = tmp_path / "a.tar.gz"
    assert run("backup", "--config", str(config), "-o", str(out), "--exclude-secrets") == 0
    assert "warning" not in capsys.readouterr().err
    files = members(out)
    text = files["config/src.yaml"].decode()
    assert "s3cret-bind" not in text and "mail-pw" not in text
    loaded = yaml.safe_load(text)
    assert loaded["directories"][0]["bind_password"] == ""
    assert loaded["mail"] == {"host": "smtp.example.org", "username": "heracles", "password": ""}
    assert loaded["directories"][0]["bind_dn"] == f"cn=admin,{BASE}"
    assert json.loads(files["manifest.json"])["config"]["secrets_excluded"] is True


def test_blank_secrets_keeps_layout_and_other_values() -> None:
    text = (
        "# the service account\n"
        "directories:\n"
        "  - id: main\n"
        "    bind_password: CHANGE_ME   # or the environment\n"
        "    uri: ldaps://ldap.example.org\n"
        "api:\n"
        "  password:\n"
        "    min_length: 12\n"
        "  database:\n"
        "    url: postgresql://heracles:hunter2@db.example.org/heracles\n"
        "  sso:\n"
        "    client_secret: |\n"
        "      line one\n"
        "      line two\n"
        "    issuer: https://idp.example.org\n"
        "# password: commented\n"
    )
    out = blank_secrets(text, "heracles.yaml")
    assert "CHANGE_ME" not in out and "hunter2" not in out and "line one" not in out
    assert "# the service account" in out and "# password: commented" in out
    loaded = yaml.safe_load(out)
    assert loaded["directories"][0] == {
        "id": "main",
        "bind_password": "",
        "uri": "ldaps://ldap.example.org",
    }
    assert loaded["api"]["password"] == {"min_length": 12}
    assert loaded["api"]["database"]["url"] == "postgresql://heracles@db.example.org/heracles"
    assert loaded["api"]["sso"] == {"client_secret": "", "issuer": "https://idp.example.org"}


def test_blank_secrets_in_toml() -> None:
    text = 'bind_password = "x"  # comment\n[mail]\nhost = "h"\npassword = "y"\n'
    out = tomllib.loads(blank_secrets(text, "heracles.toml"))
    assert out == {"bind_password": "", "mail": {"host": "h", "password": ""}}


# --- directory export ------------------------------------------------------------------------
def ldap_dns(directory: MemoryDirectory) -> set[str]:
    return {e.dn for e in directory.search(directory.base_dn, "(objectClass=*)", Scope.SUBTREE)}


def test_ldif_backup_and_restore_adds_missing_entries_and_never_deletes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = demo.build_demo_directory()
    db = Database(tmp_path / "src.db")
    db.close()
    config = write_config(tmp_path / "src.yaml", tmp_path / "src.db")
    out = tmp_path / "a.tar.gz"
    assert run("backup", "--config", str(config), "-o", str(out), "--ldif", directory=source) == 0
    manifest = json.loads(members(out)["manifest.json"])
    assert manifest["directory"]["id"] == "main" and manifest["directory"]["base_dn"] == BASE
    assert manifest["directory"]["entries"] == len(ldap_dns(source))
    capsys.readouterr()

    # a directory that lost everything but the root, and holds one entry of its own
    target = MemoryDirectory(BASE)
    root = source.get(BASE)
    assert root is not None
    target.add(BASE, {k: list(v) for k, v in root.attrs.items()})
    admin = source.get(demo.ADMIN_DN)
    assert admin is not None
    stranger = f"ou=other,{BASE}"
    target.add(stranger, {"objectClass": [b"organizationalUnit"], "ou": [b"other"]})

    dest = tmp_path / "dest.db"
    dest_config = write_config(tmp_path / "dest.yaml", dest)
    args = ("restore", str(out), "--config", str(dest_config), "--ldif")
    assert run(*args, directory=target) == 0
    printed = capsys.readouterr().out
    assert "1 already present" in printed and f"conflict {BASE}" in printed
    assert ldap_dns(target) == ldap_dns(source) | {stranger}  # extras kept, nothing deleted
    restored = target.get(demo.ADMIN_DN)
    assert restored is not None and restored.attrs == admin.attrs

    # a second run: everything exists, nothing changes, still success
    assert run(*args, "--force", directory=target) == 0
    assert f"{len(ldap_dns(source))} already present" in capsys.readouterr().out


def test_ldif_restore_refuses_another_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = demo.build_demo_directory()
    config = write_config(tmp_path / "src.yaml", tmp_path / "src.db")
    Database(tmp_path / "src.db").close()
    out = tmp_path / "a.tar.gz"
    assert run("backup", "--config", str(config), "-o", str(out), "--ldif", directory=source) == 0
    dest_config = write_config(tmp_path / "dest.yaml", tmp_path / "dest.db")
    other = MemoryDirectory("dc=other,dc=test")
    code = run("restore", str(out), "--config", str(dest_config), "--ldif", directory=other)
    assert code == 1 and "dc=other,dc=test" in capsys.readouterr().err
    assert not (tmp_path / "dest.db").exists()


# --- the real command ------------------------------------------------------------------------
def test_commands_run_as_a_subprocess(tmp_path: Path) -> None:
    db = Database(tmp_path / "src.db")
    session_id = seed(db)
    db.close()
    config = write_config(tmp_path / "src.yaml", tmp_path / "src.db")
    out = tmp_path / "a.tar.gz"
    dest_config = write_config(tmp_path / "dest.yaml", tmp_path / "dest.db")
    cli = [sys.executable, "-m", "heracles.cli.main"]
    env = {"PATH": "", "HOME": str(tmp_path)}

    done = subprocess.run(
        [*cli, "backup", "--config", str(config), "-o", str(out), "--exclude-secrets"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "wrote" in done.stdout
    done = subprocess.run(
        [*cli, "restore", str(out), "--config", str(dest_config)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    restored = Database(tmp_path / "dest.db")
    try:
        check(restored, session_id)
    finally:
        restored.close()
