"""``heracles backup`` and ``heracles restore``: the application database, the configuration
file and (optionally) the managed subtree of the directory, in one ``.tar.gz`` archive.

Layout of the archive (format version 1, see ``docs/specs/15-operations.md``)::

    manifest.json                  versions, schema numbers, contents, SHA-256 of every file
    config/<name>                  the configuration file (secrets blanked with --exclude-secrets)
    database/<table>.jsonl         one JSON object per row (the same on SQLite and PostgreSQL)
    directory/<id>.ldif            --ldif: the managed subtree of one directory
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from heracles import __version__
from heracles.cli.admin import DirectoryFactory, select_directory
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Scope
from heracles.ldap.ldif import LdifError, dump_entry, parse_ldif
from heracles.storage import Database, DatabaseError
from heracles.storage.dump import (
    check_versions,
    dump_database,
    load_database,
    table_file,
)

FORMAT_VERSION = 1
MANIFEST = "manifest.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
CHUNK = 1024 * 1024
CONFIG_ENV = "HERACLES_CONFIG"


class BackupError(Exception):
    """A backup or a restore cannot go on; the message is shown to the operator."""


# --- manifest ----------------------------------------------------------------------------------
class FileEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    kind: Literal["config", "table", "ldif"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class DatabaseInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dialect: str
    #: Schema version (migration number) of each component.
    components: dict[str, int]
    #: Rows per table.
    tables: dict[str, int]


class ConfigInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    secrets_excluded: bool


class DirectoryInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    base_dn: str
    path: str
    entries: int


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: int
    heracles_version: str
    created_at: str
    database: DatabaseInfo
    config: ConfigInfo
    directory: DirectoryInfo | None = None
    files: list[FileEntry]


# --- configuration file --------------------------------------------------------------------------
_SECRET_KEY = re.compile(r"(?:^|_)(?:password|passwd|passphrase|secret|token)$", re.IGNORECASE)
_KEY_VALUE = re.compile(
    r"^(?P<head>\s*(?:-\s+)?(?P<quote>[\"']?)(?P<key>[A-Za-z0-9_.-]+)(?P=quote)\s*[:=]\s*)"
    r"(?P<value>\S.*)$"
)
_URL_PASSWORD = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s:/@\"']+):[^\s@/\"']*@")


def config_path(args: argparse.Namespace) -> Path:
    given = args.config or os.environ.get(CONFIG_ENV)
    if not given:
        raise BackupError(f"no configuration file: use --config or ${CONFIG_ENV}")
    path = Path(given)
    if not path.is_file():
        raise BackupError(f"no such configuration file: {path}")
    return path


def _parses(path_name: str, text: str) -> bool:
    try:
        if path_name.lower().endswith(".toml"):
            tomllib.loads(text)
        else:
            yaml.safe_load(text)
    except (tomllib.TOMLDecodeError, yaml.YAMLError):
        return False
    return True


def blank_secrets(text: str, name: str) -> str:
    """The configuration with every ``*password``/``*secret``/``*token`` value emptied.

    Line based, so comments and layout survive; passwords inside URLs (``scheme://user:pw@host``)
    are dropped too. Values that are mappings or lists are left alone.
    """
    out: list[str] = []
    skip_indent: int | None = None
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        indent = len(body) - len(body.lstrip())
        if skip_indent is not None:  # the continuation lines of a blanked block scalar
            if not body.strip() or indent > skip_indent:
                continue
            skip_indent = None
        if body.lstrip().startswith("#"):
            out.append(line)
            continue
        match = _KEY_VALUE.match(body)
        if match and _SECRET_KEY.search(match["key"]):
            value = match["value"].strip()
            if not value.startswith(("{", "[", "#")):
                if value[:1] in "|>":
                    skip_indent = indent
                out.append(f'{match["head"]}""{ending}')
                continue
        out.append(_URL_PASSWORD.sub(r"\1@", body) + ending)
    result = "".join(out)
    if not _parses(name, result):
        raise BackupError("cannot blank the secrets of the configuration file safely")
    return result


def database_target(path: Path) -> Path | str:
    """Where the application database of this configuration lives (a file or a URL)."""
    from heracles.api.settings import ApiSettings
    from heracles.server import read_config

    try:
        raw = read_config(path)
        settings = ApiSettings.model_validate(raw.get("api", {}))
    except (OSError, ValueError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        raise BackupError(f"invalid configuration file {path}: {exc}") from exc
    target = settings.database.target
    if target is None:
        target = Path(os.environ.get("HERACLES_DATA_DIR", "/var/lib/heracles")) / "heracles.db"
    return target


# --- backup ------------------------------------------------------------------------------------
def _digest(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as src:
        while chunk := src.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def export_subtree(directory: DirectoryClient, dest: Path) -> int:
    """Write the managed subtree (everything under the base DN) as LDIF; return the entry count."""
    count = 0
    with dest.open("w", encoding="utf-8", newline="\n") as out:
        for entry in directory.search(directory.base_dn, "(objectClass=*)", Scope.SUBTREE):
            if count:
                out.write("\n")
            out.write(dump_entry(entry))
            count += 1
    return count


def run_backup(args: argparse.Namespace, factory: DirectoryFactory) -> int:
    try:
        config = config_path(args)
        target = database_target(config)
        if isinstance(target, Path) and not target.is_file():
            raise BackupError(f"no application database at {target}: nothing to back up")
        directory: DirectoryClient | None = None
        if args.ldif:
            directory = select_directory(args, factory)
            if directory is None:
                return 2
        out_path = Path(args.output)
        if out_path.is_dir():
            raise BackupError(f"{out_path} is a directory: give the archive file name")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="heracles-backup-") as tmp_name:
            tmp = Path(tmp_name)
            files: list[FileEntry] = []

            def add(rel: str, kind: Literal["config", "table", "ldif"]) -> None:
                sha, size = _digest(tmp / rel)
                files.append(FileEntry(path=rel, kind=kind, sha256=sha, size=size))

            (tmp / "config").mkdir()
            rel_config = f"config/{config.name}"
            text = config.read_text(encoding="utf-8")
            if args.exclude_secrets:
                text = blank_secrets(text, config.name)
            else:
                print(
                    "warning: the archive holds the secrets of the configuration file and the "
                    "password hashes, second-factor seeds and tokens of the database: keep it "
                    "private (--exclude-secrets leaves them out)",
                    file=sys.stderr,
                )
            (tmp / rel_config).write_text(text, encoding="utf-8")
            add(rel_config, "config")

            db = Database(target)
            try:
                dump = dump_database(
                    db, tmp / "database", exclude_secrets=bool(args.exclude_secrets)
                )
            finally:
                db.close()
            for table in dump.tables:
                add(table_file(table), "table")

            directory_info: DirectoryInfo | None = None
            if directory is not None:
                (tmp / "directory").mkdir()
                directory_id = _directory_id(args, directory)
                rel_ldif = f"directory/{directory_id}.ldif"
                entries = export_subtree(directory, tmp / rel_ldif)
                add(rel_ldif, "ldif")
                directory_info = DirectoryInfo(
                    id=directory_id, base_dn=directory.base_dn, path=rel_ldif, entries=entries
                )

            manifest = Manifest(
                format=FORMAT_VERSION,
                heracles_version=__version__,
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                database=DatabaseInfo(
                    dialect=dump.dialect, components=dump.components, tables=dump.tables
                ),
                config=ConfigInfo(path=rel_config, secrets_excluded=bool(args.exclude_secrets)),
                directory=directory_info,
                files=files,
            )
            _write_archive(out_path, tmp, manifest)
        rows = sum(manifest.database.tables.values())
        print(
            f"wrote {out_path}: {len(manifest.database.tables)} table(s), {rows} row(s)"
            + (f", {directory_info.entries} directory entries" if directory_info else "")
        )
    except (BackupError, DatabaseError, DirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _directory_id(args: argparse.Namespace, directory: DirectoryClient) -> str:
    wanted = getattr(args, "directory", None)
    if wanted:
        return str(wanted)
    from heracles.ldap.config import ConfigError, load_settings

    with contextlib.suppress(ConfigError, OSError, KeyError):
        settings = load_settings(args.config)
        for cfg in settings.directories:
            if cfg.base_dn == directory.base_dn:
                return cfg.id
    return "directory"


def _write_archive(out_path: Path, tmp: Path, manifest: Manifest) -> None:
    """Write the archive next to its final place and move it into position (mode 0600)."""
    fd, partial_name = tempfile.mkstemp(prefix=out_path.name + ".", dir=out_path.parent)
    partial = Path(partial_name)
    try:
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
            payload = manifest.model_dump_json(indent=2).encode("utf-8")
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(payload)
            info.mtime = int(datetime.now(UTC).timestamp())
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(payload))
            for entry in manifest.files:
                member = tar.gettarinfo(str(tmp / entry.path), arcname=entry.path)
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                member.mode = 0o600
                with (tmp / entry.path).open("rb") as src:
                    tar.addfile(member, src)
        partial.chmod(0o600)
        partial.replace(out_path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


# --- restore -----------------------------------------------------------------------------------
def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise BackupError(f"unsafe member name in the archive: {name!r}")
    return name


def verify_archive(archive: Path, dest: Path) -> Manifest:
    """Check the archive and unpack its files (hash verified) into ``dest``.

    Refuses a manifest of a newer format, a member missing, added or altered, and anything that
    is not a plain file. Nothing is written outside ``dest``.
    """
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            manifest = _unpack(tar, dest)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError(f"cannot read the archive {archive}: {exc}") from exc
    _check_manifest(manifest)
    return manifest


def _unpack(tar: tarfile.TarFile, dest: Path) -> Manifest:
    """Verify the members of the open archive and unpack them into ``dest``."""
    try:
        members = {_safe_name(m.name): m for m in tar.getmembers()}
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise BackupError(f"the archive is damaged: {exc}") from exc
    manifest_member = members.get(MANIFEST)
    if manifest_member is None or not manifest_member.isreg():
        raise BackupError("not a Heracles archive: manifest.json is missing")
    if manifest_member.size > MAX_MANIFEST_BYTES:
        raise BackupError("manifest.json is too large")
    stream = tar.extractfile(manifest_member)
    assert stream is not None
    raw = stream.read()
    try:
        document: Any = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError(f"manifest.json is not valid JSON: {exc}") from exc
    version: object = (
        cast("dict[str, object]", document).get("format") if isinstance(document, dict) else None
    )
    if not isinstance(version, int) or version < 1:
        raise BackupError("manifest.json has no valid format version")
    if version > FORMAT_VERSION:
        raise BackupError(
            f"the archive has format version {version}; this release reads up to "
            f"{FORMAT_VERSION}: upgrade Heracles before restoring"
        )
    try:
        manifest = Manifest.model_validate(document)
    except ValidationError as exc:
        raise BackupError(f"manifest.json is malformed: {exc}") from exc
    listed = {_safe_name(f.path) for f in manifest.files}
    if len(listed) != len(manifest.files):
        raise BackupError("manifest.json lists a file twice")
    extra = sorted(set(members) - listed - {MANIFEST})
    if extra:
        raise BackupError(f"the archive holds files the manifest does not list: {extra[0]}")
    for entry in manifest.files:
        member = members.get(entry.path)
        if member is None:
            raise BackupError(f"the archive lacks {entry.path}")
        if not member.isreg():
            raise BackupError(f"{entry.path} is not a regular file")
        src = tar.extractfile(member)
        assert src is not None
        target = dest / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        with target.open("wb") as out:
            while chunk := src.read(CHUNK):
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        if size != entry.size or h.hexdigest() != entry.sha256:
            raise BackupError(f"{entry.path} does not match its checksum: the archive is damaged")
    return manifest
    return manifest


def _check_manifest(manifest: Manifest) -> None:
    paths = {f.path for f in manifest.files}
    for table in manifest.database.tables:
        if table_file(table) not in paths:
            raise BackupError(f"the manifest lists no file for the table {table!r}")
    if manifest.directory is not None and manifest.directory.path not in paths:
        raise BackupError("the manifest lists no file for the directory export")
    try:
        check_versions(manifest.database.components)
    except DatabaseError as exc:
        raise BackupError(str(exc)) from exc


def _import_subtree(directory: DirectoryClient, ldif: Path) -> int:
    """Add the entries of ``ldif`` that are missing; report the others. Never deletes."""
    from heracles_plugins.ldapmanager import ldif_import as importer

    try:
        entries = parse_ldif(ldif.read_text(encoding="utf-8"))
    except (LdifError, UnicodeDecodeError) as exc:
        raise BackupError(f"the directory export is not valid LDIF: {exc}") from exc
    entries.sort(key=lambda e: dnlib.depth(e.dn))  # parents first
    results = importer.run_import(
        directory, entries, importer.ImportOptions(), allowed=lambda _dn: True, apply=True
    )
    summary = importer.summarize(results)
    print(
        f"directory: {summary['add']} added, {summary['exists']} already present (left as they "
        f"are), {summary['error']} failed"
    )
    for item in results:
        if item.action == "exists":
            print(f"  conflict {item.dn}: already exists, not changed")
    for item in results:
        if item.action == "error":
            print(f"  error    {item.dn}: {item.error}", file=sys.stderr)
    return summary["error"]


def run_restore(args: argparse.Namespace, factory: DirectoryFactory) -> int:
    failed = 0
    try:
        config = config_path(args)
        target = database_target(config)
        archive = Path(args.archive)
        with tempfile.TemporaryDirectory(prefix="heracles-restore-") as tmp_name:
            tmp = Path(tmp_name)
            manifest = verify_archive(archive, tmp)
            directory: DirectoryClient | None = None
            if args.ldif:
                if manifest.directory is None:
                    raise BackupError("the archive holds no directory export (made without --ldif)")
                directory = select_directory(args, factory)
                if directory is None:
                    return 2
                if dnlib.normalize(directory.base_dn) != dnlib.normalize(
                    manifest.directory.base_dn
                ):
                    raise BackupError(
                        f"the export is of {manifest.directory.base_dn}, the target directory "
                        f"is {directory.base_dn}"
                    )
            db = Database(target)
            try:
                result = load_database(
                    db,
                    tmp / "database",
                    manifest.database.components,
                    manifest.database.tables,
                    force=args.force,
                )
            finally:
                db.close()
            rows = sum(result.tables.values())
            print(f"database: {len(result.tables)} table(s), {rows} row(s) restored")
            if result.upgraded:
                print("database: schema upgraded for " + ", ".join(sorted(result.upgraded)))
            if directory is not None and manifest.directory is not None:
                failed = _import_subtree(directory, tmp / manifest.directory.path)
            elif manifest.directory is not None:
                print(
                    f"note: the archive holds an export of {manifest.directory.base_dn}; "
                    "use --ldif to import it"
                )
    except (BackupError, DatabaseError, DirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("sessions are not restored: everyone signs in again")
    return 1 if failed else 0


def register(sub: Any, factory: DirectoryFactory) -> None:
    """Add ``backup`` and ``restore`` to the sub-parsers object of the main parser."""
    backup = sub.add_parser(
        "backup", help="archive the application database, the configuration and the directory"
    )
    backup.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    backup.add_argument("-o", "--output", required=True, help="archive to write (.tar.gz)")
    backup.add_argument(
        "--ldif", action="store_true", help="also export the managed subtree of the directory"
    )
    backup.add_argument("--directory", help="directory id for --ldif (default: the first one)")
    backup.add_argument(
        "--exclude-secrets",
        action="store_true",
        help=(
            "blank the passwords and secrets of the archived configuration file and leave the "
            "second-factor seeds and recovery codes out of the database dump"
        ),
    )

    def do_backup(a: argparse.Namespace) -> int:
        return run_backup(a, factory)

    backup.set_defaults(func=do_backup)

    restore = sub.add_parser(
        "restore", help="load an archive made by 'backup' into the application database"
    )
    restore.add_argument("archive", help="the archive")
    restore.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    restore.add_argument(
        "--ldif", action="store_true", help="also add the archived directory entries (no deletes)"
    )
    restore.add_argument("--directory", help="directory id for --ldif (default: the first one)")
    restore.add_argument(
        "--force", action="store_true", help="replace the content of a database that holds data"
    )

    def do_restore(a: argparse.Namespace) -> int:
        return run_restore(a, factory)

    restore.set_defaults(func=do_restore)


__all__ = ["BackupError", "Manifest", "blank_secrets", "register", "verify_archive"]
