"""Setup logic shared by the setup-mode API and ``heracles init``."""

from __future__ import annotations

import contextlib
import os
import secrets
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import structlog
import yaml
from pydantic import SecretStr, ValidationError

from heracles.auth.passwords import PasswordPolicy
from heracles.core import setup_checks
from heracles.core.containers import ensure_container
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    InvalidCredentialsError,
    Scope,
)
from heracles.ldap.config import DirectoryConfig
from heracles.objects.activation import CORE_PROFILE
from heracles.schema.definitions import OBJECT_CLASSES

log = structlog.get_logger(__name__)

DATA_DIR_ENV = "HERACLES_DATA_DIR"
DEFAULT_DATA_DIR = "/var/lib/heracles"
CONFIG_FILE_NAME = "heracles.yaml"
TOKEN_FILE_NAME = "setup-token"  # noqa: S105  (a file name)
STATIC_DIR_ENV = "HERACLES_STATIC_DIR"
DEFAULT_STATIC_DIR = "/app/static"
#: Seconds allowed to reach and bind to a directory during setup.
TEST_TIMEOUT = 8.0

type ClientFactory = Callable[[DirectoryConfig], DirectoryClient]

#: Label and one-line description of the known plugins (the setup console lists them before any
#: plugin is loaded). Unknown plugin names fall back to the name.
PLUGIN_INFO: dict[str, tuple[str, str]] = {
    "posix": ("Unix accounts", "UID, home directory and shell of users; POSIX groups"),
    "ssh": ("SSH keys", "Public keys for SSH login"),
    "sudo": ("Sudo rules", "Who may run what, and where"),
    "mail": ("Mail", "Mailboxes, aliases and forwarding addresses"),
    "audit": ("Audit log", "Record who changed what, and when"),
    "acl_admin": ("Access control", "Roles and delegated administration"),
    "ppolicy": ("Password policies", "Lockout, expiry and quality rules"),
    "dns": ("DNS zones", "Zones and records served from the directory"),
    "dhcp": ("DHCP", "Services, subnets and fixed addresses"),
    "systems": ("Systems", "Servers, workstations, printers and other devices"),
    "smb_accounts": ("File sharing", "SMB accounts and domains"),
    "archive": ("Archive", "Keep a copy of deleted entries"),
    "lifecycle": ("Account lifecycle", "Arrival and departure dates, automatic deactivation"),
    "notifications": ("Notifications", "Mail on directory changes"),
    "invitations": ("Invitations", "Let people finish their own account"),
    "personal": ("Personal data", "Self-service profile fields"),
    "user_reminder": ("Password reminders", "Remind users before their password expires"),
}


class SetupError(Exception):
    """A setup step failed; ``fields`` maps form fields to messages."""

    def __init__(self, message: str, fields: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fields: dict[str, str] = dict(fields or {})


# --------------------------------------------------------------------------- paths


def data_dir() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))


def token_path() -> Path:
    return data_dir() / TOKEN_FILE_NAME


def config_path_for(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Where the configuration lives: ``explicit``, ``$HERACLES_CONFIG`` or the data directory."""
    chosen = explicit or os.environ.get("HERACLES_CONFIG")
    return Path(chosen) if chosen else data_dir() / CONFIG_FILE_NAME


def default_static_dir() -> Path | None:
    """The built console: ``$HERACLES_STATIC_DIR`` or the container image's location."""
    for candidate in (os.environ.get(STATIC_DIR_ENV), DEFAULT_STATIC_DIR):
        if candidate and (Path(candidate) / "index.html").is_file():
            return Path(candidate)
    return None


def read_raw_config(path: Path) -> dict[str, Any]:
    """The configuration mapping at ``path`` (empty when the file does not exist)."""
    if not path.is_file():
        return {}
    from heracles.server import read_config

    return dict(read_config(path))


def setup_required(config: str | os.PathLike[str] | None = None) -> bool:
    """True when no configuration with at least one directory is available."""
    chosen = config or os.environ.get("HERACLES_CONFIG")
    if not chosen:
        # a directory described by HERACLES_LDAP_* only is a complete configuration
        return not os.environ.get("HERACLES_LDAP_URI")
    path = Path(chosen)
    if not path.is_file():
        return True
    try:
        raw = read_raw_config(path)
    except Exception:  # an unreadable file is reported by the normal start, not hidden here
        return False
    return not raw.get("directories")


# ---------------------------------------------------------------------- the token


def new_token() -> str:
    return secrets.token_urlsafe(24)


def write_token(token: str) -> Path | None:
    """Store the setup token (mode 0600) in the data directory; ``None`` if it is read-only."""
    path = token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)  # a file left over with looser rights, before the write
            out.write(token + "\n")
    except OSError as exc:
        log.warning("setup_token_not_written", path=str(path), error=str(exc))
        return None
    return path


def remove_token() -> None:
    with contextlib.suppress(OSError):
        token_path().unlink()


# ----------------------------------------------------------------- the directory


@dataclass(frozen=True, slots=True)
class DirectorySpec:
    uri: str
    base_dn: str
    bind_dn: str = ""
    bind_password: str = ""
    starttls: bool = False
    ca_file: str | None = None
    id: str = "main"
    label: str = ""

    def to_config(self, *, timeout: float | None = None) -> DirectoryConfig:
        values: dict[str, Any] = {
            "id": self.id or "main",
            "label": self.label,
            "uri": self.uri,
            "bind_dn": self.bind_dn,
            "bind_password": SecretStr(self.bind_password),
            "base_dn": self.base_dn,
            "starttls": self.starttls,
            "ca_file": self.ca_file or None,
        }
        if timeout is not None:
            values["timeout"] = timeout
        return DirectoryConfig.model_validate(values)

    def to_yaml(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id or "main", "label": self.label or self.id or "main"}
        out["uri"] = self.uri
        if self.starttls:
            out["starttls"] = True
        if self.ca_file:
            out["ca_file"] = self.ca_file
        out["bind_dn"] = self.bind_dn
        out["bind_password"] = self.bind_password
        out["base_dn"] = self.base_dn
        return out


def default_client_factory(config: DirectoryConfig) -> DirectoryClient:
    from heracles.ldap.pyldap import PyLdapDirectory

    return PyLdapDirectory(config)


def required_classes() -> list[str]:
    """Every objectClass of the Heracles schema."""
    return [c.name for c in OBJECT_CLASSES]


def missing_schema_classes(installed: set[str]) -> list[str]:
    have = {c.lower() for c in installed}
    return [name for name in required_classes() if name.lower() not in have]


@dataclass(slots=True)
class DirectoryTest:
    """Outcome of :func:`test_directory`."""

    ok: bool
    error: dict[str, str] | None = None
    naming_contexts: list[str] = field(default_factory=lambda: [])
    base_dn_exists: bool = False
    can_write: bool = False
    schema_installed: bool = False
    missing_classes: list[str] = field(default_factory=lambda: [])

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "naming_contexts": self.naming_contexts,
            "base_dn_exists": self.base_dn_exists,
            "can_write": self.can_write,
            "schema": {"installed": self.schema_installed, "missing_classes": self.missing_classes},
        }


def _failure(code: str, message: str) -> DirectoryTest:
    return DirectoryTest(ok=False, error={"code": code, "message": message})


def classify_error(exc: Exception) -> tuple[str, str]:
    """``(code, readable message)`` of a failure to reach or bind to a directory."""
    text = str(exc).strip()
    lower = text.lower()
    if isinstance(exc, InvalidCredentialsError) or "invalid credentials" in lower:
        return "bad_credentials", "The directory refused the bind DN or password."
    if any(w in lower for w in ("tls", "ssl", "certificate", "starttls")):
        return "tls_error", f"The secure connection failed: {text or 'TLS error'}"
    if "timed out" in lower or "timeout" in lower:
        return "timeout", "The directory did not answer in time."
    if isinstance(exc, ValueError | ValidationError):
        return "invalid_settings", "The connection settings are not valid."
    if any(w in lower for w in ("unavailable", "can't contact", "connect", "refused", "down")):
        return "unreachable", f"Cannot reach the directory server: {text or 'no answer'}"
    return "error", f"The directory reported an error: {text or type(exc).__name__}"


def _naming_contexts(directory: DirectoryClient) -> list[str]:
    try:
        for entry in directory.search("", "(objectClass=*)", Scope.BASE, ["namingContexts"]):
            return sorted(entry.texts("namingContexts"))
    except DirectoryError:
        pass
    return []


def probe_can_write(directory: DirectoryClient) -> bool:
    """Add then delete a temporary container under the base DN."""
    name = f"heracles-setup-probe-{secrets.token_hex(4)}"
    dn = f"ou={name},{directory.base_dn}"
    try:
        directory.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [name.encode()]})
    except DirectoryError:
        return False
    try:
        directory.delete(dn)
    except DirectoryError:
        log.warning("setup_probe_not_removed", dn=dn)
    return True


def _close(directory: DirectoryClient) -> None:
    close = getattr(directory, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def test_directory(
    spec: DirectorySpec, factory: ClientFactory = default_client_factory
) -> DirectoryTest:
    """Connect, bind and inspect a directory. Never raises: a failure is ``ok=False``."""
    try:
        dnlib.normalize(spec.base_dn)
        directory = factory(spec.to_config(timeout=TEST_TIMEOUT))
    except Exception as exc:
        code, message = classify_error(exc)
        log.info("setup_directory_test_failed", uri=spec.uri, code=code)
        return _failure(code, message)
    try:
        result = _inspect(directory, spec)
    except Exception as exc:
        code, message = classify_error(exc)
        log.info("setup_directory_test_failed", uri=spec.uri, code=code)
        return _failure(code, message)
    finally:
        _close(directory)
    log.info(
        "setup_directory_tested",
        uri=spec.uri,
        base_dn_exists=result.base_dn_exists,
        can_write=result.can_write,
        schema_installed=result.schema_installed,
    )
    return result


test_directory.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def _inspect(directory: DirectoryClient, spec: DirectorySpec) -> DirectoryTest:
    exists = directory.get(spec.base_dn, ["objectClass"]) is not None  # also binds
    result = DirectoryTest(
        ok=True, naming_contexts=_naming_contexts(directory), base_dn_exists=exists
    )
    result.can_write = exists and probe_can_write(directory)
    try:
        missing = missing_schema_classes(directory.schema_object_classes())
    except Exception:
        missing = required_classes()
    result.missing_classes = missing
    result.schema_installed = not missing
    return result


# ------------------------------------------------------------------------ plugins


def plugin_catalog() -> dict[str, Any]:
    """Profiles and plugins offered by the setup (``GET /plugins``)."""
    from heracles.objects.registry import discover_plugins

    names = sorted({p.name for p in discover_plugins()})
    core = [n for n in CORE_PROFILE if n in names]
    return {
        "profiles": [{"id": "core", "plugins": core}, {"id": "all", "plugins": names}],
        "plugins": [
            {
                "name": n,
                "label": PLUGIN_INFO.get(n, (n, ""))[0],
                "description": PLUGIN_INFO.get(n, (n, ""))[1],
                "default": n in core,
            }
            for n in names
        ],
    }


def resolve_plugins(spec: str | None) -> list[str]:
    """``core``, ``all`` or a comma separated list of plugin names."""
    catalog = plugin_catalog()
    known = {p["name"] for p in catalog["plugins"]}
    wanted = (spec or "core").strip()
    for profile in catalog["profiles"]:
        if profile["id"] == wanted:
            return list(profile["plugins"])
    names = [n.strip() for n in wanted.split(",") if n.strip()]
    unknown = [n for n in names if n not in known]
    if unknown:
        raise SetupError(
            f"unknown plugin(s): {', '.join(unknown)}", {"plugins": ", ".join(unknown)}
        )
    return names


# -------------------------------------------------------------------------- apply


@dataclass(frozen=True, slots=True)
class AdminSpec:
    uid: str
    password: str
    given_name: str = "Administrator"
    surname: str = "Admin"
    mail: str = ""


@dataclass(frozen=True, slots=True)
class ApplyResult:
    config_path: Path
    admin_dn: str
    admin_created: bool


def _validate(
    directory: DirectorySpec, admin: AdminSpec, plugins: list[str], public_url: str | None
) -> None:
    fields: dict[str, str] = {}
    if not directory.uri.lower().startswith(("ldap://", "ldaps://", "ldapi://")):
        fields["directory.uri"] = "Use an ldap:// or ldaps:// address."
    try:
        if not dnlib.split(directory.base_dn):
            fields["directory.base_dn"] = "The base DN is required."
    except Exception:
        fields["directory.base_dn"] = "This is not a valid DN."
    if not admin.uid.strip():
        fields["admin.uid"] = "The login is required."
    elif any(c in admin.uid for c in ',=+"\\<>;# /'):
        fields["admin.uid"] = "Use letters, digits, dots, dashes and underscores."
    if admin.mail and ("@" not in admin.mail or " " in admin.mail):
        fields["admin.mail"] = "This is not a valid address."
    problems = PasswordPolicy().problems(admin.password)
    if problems:
        fields["admin.password"] = "; ".join(problems)
    if public_url:
        parts = urlsplit(public_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            fields["public_url"] = "Use a full address such as https://heracles.example.org."
    if not plugins:
        fields["plugins"] = "Choose at least one plugin."
    if fields:
        raise SetupError("Some fields are not valid", fields)


def build_config(
    existing: Mapping[str, Any],
    directory: DirectorySpec,
    admin_dn: str,
    plugins: list[str],
    public_url: str | None,
) -> dict[str, Any]:
    """The configuration to write: ``existing`` with the directory, admin and plugins set."""
    config: dict[str, Any] = dict(existing)
    config["directories"] = [directory.to_yaml()]
    api: dict[str, Any] = dict(cast("Mapping[str, Any]", config.get("api") or {}))
    api["admin_dns"] = [admin_dn]
    session: dict[str, Any] = dict(cast("Mapping[str, Any]", api.get("session") or {}))
    session["cookie_secure"] = not (public_url or "").lower().startswith("http://")
    api["session"] = session
    if public_url:
        host = urlsplit(public_url).hostname
        if host:
            api["allowed_hosts"] = [host]
    static = default_static_dir()
    if static is not None and "static_dir" not in api:
        api["static_dir"] = str(static)
    config["api"] = api
    config["plugins"] = {"enabled": plugins}
    return config


def write_config(path: Path, config: Mapping[str, Any]) -> None:
    """Write ``config`` as YAML with mode 0600 (it holds the bind password), atomically."""
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise SetupError(f"{path}: the setup writes YAML; use a .yaml configuration file")
    header = "# Written by the Heracles setup. Holds the bind password: keep it private.\n"
    body = yaml.safe_dump(dict(config), sort_keys=False, default_flow_style=False)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".heracles-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(header + body)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except OSError as exc:
        raise SetupError(f"cannot write {path}: {exc.strerror or exc}") from exc


def prepare_directory(client: DirectoryClient, admin: AdminSpec) -> tuple[str, bool]:
    """Create the standard containers and the administrator; ``(admin DN, created)``."""
    if client.get(client.base_dn, ["objectClass"]) is None:
        raise SetupError(
            "The base DN does not exist", {"directory.base_dn": "This entry does not exist."}
        )
    ctx = setup_checks.context_for(client)
    policy = PasswordPolicy()
    admin_dn = (
        f"uid={dnlib.escape_rdn_value(admin.uid)},{dnlib.join(ctx.users_rdn, client.base_dn)}"
    )
    try:
        for rdn in (ctx.users_rdn, ctx.groups_rdn, ctx.roles_rdn):
            ensure_container(client, dnlib.join(rdn, client.base_dn))
        if client.get(admin_dn, ["objectClass"]) is not None:
            return admin_dn, False
        admin_dn = setup_checks.create_admin_user(
            ctx,
            admin.uid,
            password_hash=policy.hash_new(admin.password),
            given_name=admin.given_name or "Administrator",
            surname=admin.surname or "Admin",
            mail=admin.mail,
        )
    except DirectoryError as exc:
        raise SetupError(f"The directory refused a change: {exc}") from exc
    return admin_dn, True


def apply_setup(
    directory: DirectorySpec,
    admin: AdminSpec,
    plugins: list[str],
    public_url: str | None,
    config_path: Path,
    factory: ClientFactory = default_client_factory,
) -> ApplyResult:
    """Validate, prepare the directory, create the administrator and write the configuration."""
    _validate(directory, admin, plugins, public_url)
    known = {p["name"] for p in plugin_catalog()["plugins"]}
    unknown = [p for p in plugins if p not in known and p != "*"]
    if unknown:
        raise SetupError(
            "Some fields are not valid", {"plugins": f"Unknown plugin(s): {', '.join(unknown)}"}
        )
    try:
        client = factory(directory.to_config(timeout=TEST_TIMEOUT))
    except Exception as exc:
        raise SetupError("Cannot use these connection settings", {"directory": str(exc)}) from exc
    try:
        admin_dn, created = prepare_directory(client, admin)
    except SetupError:
        raise
    except Exception as exc:
        _code, message = classify_error(exc)
        raise SetupError(message, {"directory": message}) from exc
    finally:
        _close(client)
    config = build_config(read_raw_config(config_path), directory, admin_dn, plugins, public_url)
    write_config(config_path, config)
    log.info(
        "setup_applied",
        config=str(config_path),
        admin=admin_dn,
        admin_created=created,
        plugins=plugins,
    )
    return ApplyResult(config_path, admin_dn, created)


def record_setup_audit(app: Any, admin_dn: str, base_dn: str, client_ip: str = "") -> None:
    """The ``config`` audit event of a finished setup (no-op without the audit plugin)."""
    domain = getattr(app.state, "domain", None)
    state = getattr(app.state, "heracles", None)
    if domain is None or state is None or not state.directories:
        return
    directory = next(iter(state.directories.values()))
    domain.audit.record(
        directory,
        "config",
        object_type="setup",
        object_dn=base_dn,
        author_dn=admin_dn,
        author_ip=client_ip,
        attributes=["initial setup completed"],
        source="setup",
    )
