# ruff: noqa: S105
"""Configuration stored in the directory, merged with the YAML settings.

The main configuration entry lives at ``cn=config`` below the application
container. YAML settings provide the defaults and bootstrap values; when the
entry holds a value for a knob that exists in both, the directory wins.

Contract used by other modules::

    effective_settings(directory) -> RuntimeConfig

The result is cached per directory (short TTL) and invalidated on every save
through :func:`save_config`.
"""

from __future__ import annotations

import contextlib
import threading
import time
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

from heracles.auth.passwords.registry import default_registry
from heracles.core.containers import ensure_container
from heracles.core.formats import check
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
)
from heracles.schema import names as schema

type Kind = Literal["str", "text", "int", "bool", "list", "select", "path"]

CACHE_TTL_SECONDS: Final = 30.0
#: How long the fallback of an unreadable configuration entry is reused.
FAILURE_TTL_SECONDS: Final = 2.0
_TRUE: Final = "TRUE"
_FALSE: Final = "FALSE"

#: Largest numeric identifier (``uidNumber`` and ``gidNumber`` are 32-bit).
MAX_ID: Final = 2**32 - 1

#: Hash schemes the password module can produce (the only ones a policy may name).
PASSWORD_HASHES: Final = tuple(default_registry().hashable_ids())

#: Sections of the configuration screen, in display order.
SECTIONS: Final = (
    "look_and_feel",
    "core",
    "password",
    "login",
    "ssl",
    "storage",
    "snapshots",
    "triggers",
    "recovery",
    "tasks",
    "mail_templates",
    "debugging",
    "misc",
)


#: Login shells offered by the POSIX tab until the configuration lists others (the same list
#: the plugin ships), and the one given to new accounts.
DEFAULT_SHELLS: Final = (
    "/bin/bash",
    "/bin/sh",
    "/bin/zsh",
    "/usr/bin/fish",
    "/bin/false",
    "/usr/sbin/nologin",
)
DEFAULT_SHELL: Final = "/bin/bash"


@dataclass(frozen=True, slots=True)
class ConfigField:
    """Metadata of one configuration knob.

    The constraints (``min``, ``max``, ``format``, ``item_format``, ``unique``, and the
    ``options`` of a select or of a list) are checked on every write and exposed to the
    browser, which refuses the same values before saving. Stored values are never
    checked when read. An empty value is always allowed: it removes the attribute, which
    restores the default.
    """

    key: str
    section: str
    kind: Kind = "str"
    #: True when Heracles acts on the value; False means "stored for compatibility".
    honoured: bool = False
    options: tuple[str, ...] = ()
    #: Value hidden from users who cannot write the configuration.
    secret: bool = False
    default: Any = None
    #: Bounds of an ``int`` (inclusive).
    min: int | None = None
    max: int | None = None
    #: Name of a :mod:`heracles.core.formats` check on a text value.
    format: str | None = None
    #: Same, for every entry of a ``list``.
    item_format: str | None = None
    #: A ``list`` without repeated entries.
    unique: bool = False

    @property
    def attr(self) -> str:
        return schema.CONFIG_ATTRS[self.key]

    def constraints(self) -> dict[str, Any]:
        """The constraints that apply, by name (only those set)."""
        found: dict[str, Any] = {
            "min": self.min,
            "max": self.max,
            "format": self.format,
            "item_format": self.item_format,
            "unique": self.unique or None,
        }
        return {k: v for k, v in found.items() if v is not None}


def _f(
    key: str,
    section: str,
    kind: Kind = "str",
    *,
    honoured: bool = False,
    options: Sequence[str] = (),
    secret: bool = False,
    default: Any = None,
    min: int | None = None,
    max: int | None = None,
    format: str | None = None,
    item_format: str | None = None,
    unique: bool = False,
) -> ConfigField:
    # a number is never negative unless a knob says otherwise
    if kind == "int" and min is None:
        min = 0
    return ConfigField(
        key,
        section,
        kind,
        honoured,
        tuple(options),
        secret,
        default,
        min,
        max,
        format,
        item_format,
        unique,
    )


CONFIG_FIELDS: Final[tuple[ConfigField, ...]] = (
    # --- look and feel
    _f("language", "look_and_feel", "select", options=("en", "fr"), default="en"),
    _f("theme", "look_and_feel"),
    _f("timezone", "look_and_feel", default="UTC", format="timezone"),
    _f("list_summary", "look_and_feel", "bool"),
    _f("store_filter_settings", "look_and_feel", "bool"),
    _f("max_avatar_size", "look_and_feel", "int", default=200, min=1),
    # --- core
    _f("schema_check", "core", "bool"),
    _f("account_primary_attribute", "core", "select", options=("uid", "cn"), default="uid"),
    _f("next_id_hook", "core", "path", format="abs_path"),
    _f("strict_naming_rules", "core", "bool"),
    _f("min_id", "core", "int", honoured=True, default=1000, max=MAX_ID),
    _f("uid_number_base", "core", honoured=True, default="1100", format="id_range"),
    _f("gid_number_base", "core", honoured=True, default="1100", format="id_range"),
    _f(
        "id_allocation_method",
        "core",
        "select",
        options=("traditional", "pool"),
        default="traditional",
    ),
    _f("uid_pool_min", "core", "int", max=MAX_ID),
    _f("uid_pool_max", "core", "int", max=MAX_ID),
    _f("gid_pool_min", "core", "int", max=MAX_ID),
    _f("gid_pool_max", "core", "int", max=MAX_ID),
    _f("cn_pattern", "core"),
    _f("restrict_role_members", "core", "bool"),
    _f("given_name_required", "core", "bool"),
    _f("split_postal_address", "core", "bool"),
    _f("postal_address_pattern", "core"),
    #: 0 lifts the limit (the directory client's convention).
    _f("ldap_size_limit", "core", "int", default=200),
    _f("wildcard_foreign_keys", "core", "bool"),
    _f("modification_detection_attribute", "core", format="attribute"),
    _f(
        "shells",
        "core",
        "list",
        honoured=True,
        default=list(DEFAULT_SHELLS),
        item_format="abs_path",
        unique=True,
    ),
    _f("default_shell", "core", honoured=True, default=DEFAULT_SHELL, format="abs_path"),
    _f("mail_domain", "core", honoured=True, default="", format="domain"),
    _f("acl_tab_on_objects", "core", "bool"),
    _f("department_categories", "core", "list"),
    _f("plugins_menu_blacklist", "core", "list"),
    _f("acl_target_filter_limit", "core", "int", honoured=True, default=100, min=1),
    _f("management_config", "core", "list"),
    _f("management_user_config", "core", "list"),
    _f("incremental_modifier_states", "core", "text"),
    _f("ogroup_default_user", "core", "bool"),
    _f("force_sasl_password_ask", "core", "bool"),
    # --- password
    _f(
        "password_default_hash",
        "password",
        "select",
        honoured=True,
        options=PASSWORD_HASHES,
        default="ssha",
    ),
    _f(
        "password_allowed_hashes",
        "password",
        "list",
        honoured=True,
        options=PASSWORD_HASHES,
        unique=True,
    ),
    _f("force_password_default_hash", "password", "bool", honoured=True),
    _f("password_min_length", "password", "int", honoured=True, default=8, min=1, max=1024),
    _f("password_min_differ", "password", "int", honoured=True, default=0, max=1024),
    _f("handle_expired_accounts", "password", "bool"),
    _f("sasl_realm", "password"),
    _f("sasl_exop", "password"),
    # --- login and session
    _f("login_attribute", "login", honoured=True, default="uid", format="attribute"),
    _f("session_lifetime", "login", "int", honoured=True, default=1800, min=60, max=31_536_000),
    _f(
        "login_method",
        "login",
        "select",
        options=("form", "http_basic", "http_header", "cas"),
        default="form",
    ),
    _f("http_auth_enabled", "login", "bool"),
    _f("http_header_auth_enabled", "login", "bool"),
    _f("http_header_name", "login", default="AUTH_USER", format="http_header"),
    _f("cas_enabled", "login", "bool"),
    _f("cas_host", "login", format="hostname"),
    _f("cas_port", "login", "int", min=1, max=65535),
    _f("cas_context", "login"),
    _f("cas_ca_cert_path", "login", "path", format="abs_path"),
    _f("cas_verbose", "login", "bool"),
    _f("cas_new_library", "login", "bool"),
    _f("cas_service_name", "login"),
    # --- ssl
    _f("force_ssl", "ssl", "bool"),
    _f("warn_ssl", "ssl", "bool"),
    _f("ssl_ca_cert_path", "ssl", "path", format="abs_path"),
    _f("ssl_key_path", "ssl", "path", format="abs_path"),
    _f("ssl_cert_path", "ssl", "path", format="abs_path"),
    # --- storage (RDNs)
    _f("user_rdn", "storage", honoured=True, default="ou=people", format="rdn"),
    _f("group_rdn", "storage", honoured=True, default="ou=groups", format="rdn"),
    _f("acl_role_rdn", "storage", honoured=True, default="ou=aclroles", format="rdn"),
    _f("ogroup_rdn", "storage", format="rdn"),
    _f("token_rdn", "storage", format="rdn"),
    _f("orchestrator_token_rdn", "storage", format="rdn"),
    _f("recovery_token_rdn", "storage", format="rdn"),
    # --- snapshots
    _f("snapshots_enabled", "snapshots", "bool", default=True),
    _f("snapshot_base", "snapshots", honoured=True, format="dn"),
    _f("automatic_snapshots", "snapshots", "bool"),
    _f("snapshot_min_retention", "snapshots", "int"),
    _f("snapshot_retention_days", "snapshots", "int"),
    _f("snapshot_source_data", "snapshots"),
    # --- triggers (the hook list has its own structured editor)
    _f("tab_hooks", "triggers", "list", honoured=True),
    _f("display_hook_output", "triggers", "bool", honoured=True),
    # --- password recovery
    _f("recovery_enabled", "recovery", "bool"),
    _f("recovery_email", "recovery", format="email"),
    _f("recovery_mail_subject", "recovery"),
    _f("recovery_mail_body", "recovery", "text"),
    _f("recovery_mail2_subject", "recovery"),
    _f("recovery_mail2_body", "recovery", "text"),
    _f("recovery_validity", "recovery", "int", default=10, min=1),
    _f("recovery_salt", "recovery", secret=True),
    _f("recovery_use_alternate", "recovery", "bool"),
    _f("recovery_login_attribute", "recovery", default="uid", format="attribute"),
    # --- tasks
    _f("tasks_rdn", "tasks", format="rdn"),
    _f("tasks_last_exec_time", "tasks"),
    _f("tasks_max_emails", "tasks", "int"),
    _f("tasks_interval_emails", "tasks", "int"),
    # --- mail templates
    _f("mail_template_rdn", "mail_templates", format="rdn"),
    # --- debugging
    _f("display_errors", "debugging", "bool"),
    _f("ldap_max_query_time", "debugging", "int"),
    _f("ldap_stats", "debugging", "bool"),
    _f("debug_level", "debugging", "int"),
    _f("debug_logging", "debugging", "bool"),
    _f("logging", "debugging", "bool"),
    # --- miscellaneous
    _f("dashboard_prefix", "misc", "list"),
    _f("dashboard_digits", "misc", "int"),
    _f("dashboard_expired_days", "misc", "int"),
    _f("config_checksum", "misc", "list"),
)

FIELDS_BY_KEY: Final = {f.key: f for f in CONFIG_FIELDS}
_FIELDS_BY_ATTR: Final = {f.attr.lower(): f for f in CONFIG_FIELDS}


class ConfigError(ValueError):
    """An invalid configuration value."""

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = dict(fields)


# --------------------------------------------------------------------- locations


def config_dn(directory: DirectoryClient) -> str:
    """DN of the main configuration entry."""
    return f"{schema.CONFIG_RDN},{schema.APP_OU},{directory.base_dn}"


# --------------------------------------------------------------------- YAML side


@dataclass(slots=True)
class YamlDefaults:
    """The YAML settings relevant to the runtime configuration (bootstrap values)."""

    login_attribute: str = "uid"
    session_lifetime: int = 1800
    password_default_hash: str = "ssha"
    password_allowed_hashes: list[str] = field(default_factory=lambda: [])
    force_password_default_hash: bool = False
    password_min_length: int = 8
    password_min_differ: int = 0
    http_header_auth_enabled: bool = False
    http_header_name: str = "AUTH_USER"
    recovery_enabled: bool = True
    recovery_validity: int = 10


_yaml_defaults = YamlDefaults()


def set_yaml_defaults(defaults: YamlDefaults) -> None:
    """Register the YAML defaults used when ``effective_settings`` has none passed."""
    global _yaml_defaults
    _yaml_defaults = defaults


# --------------------------------------------------------------------- conversions


def _decode(kind: Kind, raw: list[str]) -> Any:
    """LDAP text values -> typed value (``None`` when the attribute is absent/unusable)."""
    if kind == "list":
        return list(raw)
    if not raw:
        return None
    first = raw[0]
    if kind == "bool":
        return first.strip().upper() == _TRUE
    if kind == "int":
        try:
            return int(first.strip())
        except ValueError:
            return None
    return first


def _encode(kind: Kind, value: Any) -> list[str]:
    """Typed value -> LDAP text values (empty list means "remove the attribute")."""
    if value is None:
        return []
    if kind == "list":
        return [str(v) for v in value if str(v) != ""]
    if kind == "bool":
        return [_TRUE if value else _FALSE]
    if kind == "int":
        return [str(int(value))]
    text = str(value)
    return [text] if text != "" else []


def _validate(field_: ConfigField, value: Any) -> str | None:
    """Return an error message for an invalid typed value, else ``None``."""
    if value is None:
        return None
    if field_.kind == "bool" and not isinstance(value, bool):
        return "Expected a boolean."
    if field_.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return "Expected a whole number."
        if field_.min is not None and value < field_.min:
            return "Must not be negative." if field_.min == 0 else f"Must be at least {field_.min}."
        if field_.max is not None and value > field_.max:
            return f"Must be at most {field_.max}."
    if field_.kind == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):  # pyright: ignore[reportUnknownVariableType]
            return "Expected a list of strings."
        return _validate_items(field_, cast("list[str]", value))
    if field_.kind in ("str", "text", "path", "select") and not isinstance(value, str):
        return "Expected a string."
    if field_.kind == "select" and value != "" and value not in field_.options:
        return "Unknown option."
    if field_.format is not None and isinstance(value, str):
        return check(field_.format, value)
    return None


def _validate_items(field_: ConfigField, items: list[str]) -> str | None:
    seen: set[str] = set()
    for item in items:
        if item == "":
            continue
        if field_.options and item not in field_.options:
            return f"Unknown option: {item}."
        if field_.item_format is not None:
            message = check(field_.item_format, item)
            if message is not None:
                return f"{item}: {message}"
        if field_.unique and item in seen:
            return f"Duplicate entry: {item}."
        seen.add(item)
    return None


# --------------------------------------------------------------------- reading


@dataclass(slots=True)
class ConfigSnapshot:
    """What the directory holds: typed values by key, plus unknown attributes."""

    exists: bool
    values: dict[str, Any] = field(default_factory=lambda: {})
    object_classes: list[str] = field(default_factory=lambda: [])


def read_config(directory: DirectoryClient) -> ConfigSnapshot:
    """Read the configuration entry (missing entry -> empty snapshot)."""
    try:
        entry = directory.get(config_dn(directory))
    except NoSuchObjectError:
        entry = None
    if entry is None:
        return ConfigSnapshot(False)
    return snapshot_of(entry)


def snapshot_of(entry: Entry) -> ConfigSnapshot:
    values: dict[str, Any] = {}
    for f in CONFIG_FIELDS:
        raw = entry.texts(f.attr)
        if not raw:
            continue
        decoded = _decode(f.kind, raw)
        if decoded is not None:
            values[f.key] = decoded
    return ConfigSnapshot(True, values, entry.texts("objectClass"))


@dataclass(slots=True)
class RuntimeConfig:
    """Effective settings: YAML defaults overridden by the directory.

    ``values`` holds every known key (typed per kind); the named fields are
    shortcuts for the knobs other modules consume.
    """

    values: dict[str, Any]
    #: Keys whose value comes from the directory (the others are defaults).
    from_directory: frozenset[str] = frozenset()
    login_attribute: str = "uid"
    login_method: str = "form"
    http_auth_enabled: bool = False
    http_header_auth_enabled: bool = False
    http_header_name: str = "AUTH_USER"
    cas_enabled: bool = False
    cas_host: str = ""
    cas_port: int | None = None
    cas_context: str = ""
    cas_ca_cert_path: str = ""
    cas_verbose: bool = False
    cas_new_library: bool = False
    cas_service_name: str = ""
    session_lifetime: int = 1800
    password_default_hash: str = "ssha"
    password_allowed_hashes: list[str] = field(default_factory=lambda: [])
    force_password_default_hash: bool = False
    password_min_length: int = 8
    password_min_differ: int = 0
    snapshots_enabled: bool = True
    snapshot_base: str | None = None
    snapshot_min_retention: int | None = None
    snapshot_retention_days: int | None = None
    user_rdn: str = "ou=people"
    group_rdn: str = "ou=groups"
    acl_role_rdn: str = "ou=aclroles"
    uid_number_base: str = "1100"
    gid_number_base: str = "1100"
    min_id: int = 1000
    shells: list[str] = field(default_factory=lambda: list(DEFAULT_SHELLS))
    default_shell: str = DEFAULT_SHELL
    mail_domain: str = ""
    language: str = "en"
    timezone: str = "UTC"
    ldap_size_limit: int = 200
    acl_target_filter_limit: int = 100
    tab_hooks: list[str] = field(default_factory=lambda: [])
    display_hook_output: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


_SHORTCUTS: Final = (
    "login_attribute",
    "login_method",
    "http_auth_enabled",
    "http_header_auth_enabled",
    "http_header_name",
    "cas_enabled",
    "cas_host",
    "cas_port",
    "cas_context",
    "cas_ca_cert_path",
    "cas_verbose",
    "cas_new_library",
    "cas_service_name",
    "session_lifetime",
    "password_default_hash",
    "password_allowed_hashes",
    "force_password_default_hash",
    "password_min_length",
    "password_min_differ",
    "snapshots_enabled",
    "snapshot_base",
    "snapshot_min_retention",
    "snapshot_retention_days",
    "user_rdn",
    "group_rdn",
    "acl_role_rdn",
    "uid_number_base",
    "gid_number_base",
    "min_id",
    "shells",
    "default_shell",
    "mail_domain",
    "language",
    "timezone",
    "ldap_size_limit",
    "acl_target_filter_limit",
    "tab_hooks",
    "display_hook_output",
)


def merge(snapshot: ConfigSnapshot, yaml: YamlDefaults | None = None) -> RuntimeConfig:
    """Merge directory values over the YAML defaults."""
    y = yaml or _yaml_defaults
    values: dict[str, Any] = {}
    for f in CONFIG_FIELDS:
        if f.default is not None:
            default: Any = f.default
            values[f.key] = (
                list(cast("list[Any]", default)) if isinstance(default, list) else default
            )
        elif f.kind == "list":
            values[f.key] = []
    values.update(
        {
            "login_attribute": y.login_attribute,
            "session_lifetime": y.session_lifetime,
            "password_default_hash": y.password_default_hash,
            "password_allowed_hashes": list(y.password_allowed_hashes),
            "force_password_default_hash": y.force_password_default_hash,
            "password_min_length": y.password_min_length,
            "password_min_differ": y.password_min_differ,
            "http_header_auth_enabled": y.http_header_auth_enabled,
            "http_header_name": y.http_header_name,
            "recovery_enabled": y.recovery_enabled,
            "recovery_validity": y.recovery_validity,
        }
    )
    values.update(snapshot.values)
    if "login_method" not in snapshot.values:
        if values.get("cas_enabled"):
            values["login_method"] = "cas"
        elif values.get("http_header_auth_enabled"):
            values["login_method"] = "http_header"
        elif values.get("http_auth_enabled"):
            values["login_method"] = "http_basic"
    config = RuntimeConfig(values=values, from_directory=frozenset(snapshot.values))
    for key in _SHORTCUTS:
        if key in values:
            setattr(config, key, values[key])
    config.snapshot_base = values.get("snapshot_base") or None
    return config


# --------------------------------------------------------------------- cache

_lock = threading.Lock()
_cache: weakref.WeakKeyDictionary[Any, tuple[float, RuntimeConfig]] = weakref.WeakKeyDictionary()


def invalidate(directory: DirectoryClient) -> None:
    """Forget the cached configuration of ``directory``."""
    with _lock, contextlib.suppress(TypeError):
        _cache.pop(directory, None)


def effective_settings(
    directory: DirectoryClient, yaml: YamlDefaults | None = None
) -> RuntimeConfig:
    """YAML settings merged with the configuration entry of ``directory``.

    A directory that cannot be read (or has no entry) yields the YAML values.
    """
    now = time.monotonic()
    if yaml is None:
        with _lock:
            try:
                hit = _cache.get(directory)
            except TypeError:
                hit = None
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    unreadable = False
    try:
        snapshot = read_config(directory)
    except Exception:  # an unreachable entry must not break callers
        snapshot = ConfigSnapshot(False)
        unreadable = True
    config = merge(snapshot, yaml)
    if yaml is None:
        # the YAML fallback of a failed read is kept for a moment only: the stricter values
        # stored in the directory (password policy, ...) must not be lost for the whole TTL
        stamp = now - (CACHE_TTL_SECONDS - FAILURE_TTL_SECONDS) if unreadable else now
        with _lock, contextlib.suppress(TypeError):
            _cache[directory] = (stamp, config)
    return config


# --------------------------------------------------------------------- writing


def _plan(snapshot_entry: Entry | None, changes: Mapping[str, Any]) -> list[Modification]:
    """Modifications that turn the stored attributes into ``changes`` (only differences)."""
    mods: list[Modification] = []
    for key, value in changes.items():
        f = FIELDS_BY_KEY[key]
        wanted = _encode(f.kind, value)
        current = snapshot_entry.texts(f.attr) if snapshot_entry is not None else []
        if f.kind == "list":
            same = sorted(current) == sorted(wanted)
        else:
            same = current == wanted or (
                f.kind == "bool" and [c.upper() for c in current] == [w.upper() for w in wanted]
            )
        if same:
            continue
        if not wanted:
            mods.append(Modification("delete", f.attr))
        else:
            mods.append(Modification("replace", f.attr, [w.encode("utf-8") for w in wanted]))
    return mods


def _effective_values(
    snapshot: ConfigSnapshot | None, changes: Mapping[str, Any]
) -> dict[str, Any]:
    """Values in force once ``changes`` are written (an emptied key falls back to its default)."""
    values = dict(snapshot.values) if snapshot is not None else {}
    for key, value in changes.items():
        values.pop(key, None)
        f = FIELDS_BY_KEY.get(key)
        if f is not None and f.kind != "bool" and value in (None, "", []):
            continue
        if value is not None:
            values[key] = value
    return merge(ConfigSnapshot(True, values)).values


def _int_of(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _id_range_end(value: Any) -> int | None:
    """Upper bound of an ``a-b`` identifier range (``None`` for a plain base or garbage)."""
    if not isinstance(value, str) or check("id_range", value) is not None:
        return None
    _low, sep, high = value.partition("-")
    return int(high) if sep else None


def _cross_errors(changes: Mapping[str, Any], effective: Mapping[str, Any]) -> dict[str, str]:
    """Rules that tie several keys together, checked on the values in force after the write.

    A rule runs only when one of its keys is being written, so a stored value that predates
    the rule never blocks an unrelated save. The error goes to the key being written; when
    both are, to the dependent one (the first of each pair below).
    """
    errors: dict[str, str] = {}

    def report(dependent: str, other: str, on_dependent: str, on_other: str) -> None:
        if dependent not in changes and other not in changes:
            return
        if dependent in changes or other not in changes:
            errors.setdefault(dependent, on_dependent)
        else:
            errors.setdefault(other, on_other)

    shells: list[str] = effective.get("shells") or []
    default_shell = effective.get("default_shell")
    if shells and default_shell and default_shell not in shells:
        report(
            "default_shell",
            "shells",
            "Must be one of the listed shells.",
            f"Must include the default shell ({default_shell}).",
        )
    allowed: list[str] = effective.get("password_allowed_hashes") or []
    default_hash = effective.get("password_default_hash")
    if allowed and default_hash and default_hash not in allowed:
        report(
            "password_default_hash",
            "password_allowed_hashes",
            "Must be one of the allowed hashes.",
            f"Must include the default hash ({default_hash}).",
        )
    length = _int_of(effective.get("password_min_length"))
    differ = _int_of(effective.get("password_min_differ"))
    if length is not None and differ is not None and differ > length:
        report(
            "password_min_differ",
            "password_min_length",
            f"Must not exceed the minimum length ({length}).",
            f"Must be at least the number of differing characters ({differ}).",
        )
    for kind in ("uid", "gid"):
        low = _int_of(effective.get(f"{kind}_pool_min"))
        high = _int_of(effective.get(f"{kind}_pool_max"))
        if low is not None and high is not None and low > high:
            report(
                f"{kind}_pool_max",
                f"{kind}_pool_min",
                f"Must not be below the minimum ({low}).",
                f"Must not exceed the maximum ({high}).",
            )
    min_id = _int_of(effective.get("min_id"))
    for kind in ("uid", "gid"):
        end = _id_range_end(effective.get(f"{kind}_number_base"))
        if end is not None and min_id is not None and end <= min_id:
            report(
                f"{kind}_number_base",
                "min_id",
                f"The range must end above the minimum identifier ({min_id}).",
                f"Must be below the end of the {kind} identifier range ({end}).",
            )
    return errors


def validate_changes(
    changes: Mapping[str, Any], current: ConfigSnapshot | None = None
) -> dict[str, Any]:
    """Check keys, types and constraints; returns the changes or raises :class:`ConfigError`.

    ``current`` is what the directory holds: the rules that tie several keys together are
    checked on the values in force after the write (stored ones where unchanged).
    """
    errors: dict[str, str] = {}
    for key, value in changes.items():
        f = FIELDS_BY_KEY.get(key)
        if f is None:
            errors[key] = "Unknown setting."
            continue
        message = _validate(f, value)
        if message is not None:
            errors[key] = message
    if not errors:
        for key, message in _cross_errors(changes, _effective_values(current, changes)).items():
            errors.setdefault(key, message)
    if errors:
        raise ConfigError(errors)
    return dict(changes)


def save_config(directory: DirectoryClient, changes: Mapping[str, Any]) -> list[str]:
    """Write ``changes`` (key -> typed value) to the configuration entry.

    Only attributes whose value differs are modified; unknown attributes of the
    entry are never touched. The entry (and its auxiliary classes) is created
    when needed. Returns the keys that were actually written.
    """
    validated = validate_changes(changes, read_config(directory))
    dn = config_dn(directory)
    try:
        entry = directory.get(dn)
    except NoSuchObjectError:
        entry = None
    mods = _plan(entry, validated)
    written = [
        k
        for k, f in ((k, FIELDS_BY_KEY[k]) for k in validated)
        if any(m.attr == f.attr for m in mods)
    ]
    if not mods:
        return []
    needed_classes = [
        schema.CONFIG_ATTR_CLASS[m.attr]
        for m in mods
        if m.op == "replace" and m.attr in schema.CONFIG_ATTR_CLASS
    ]
    if entry is None:
        ensure_container(directory, f"{schema.APP_OU},{directory.base_dn}")
        classes = [schema.OC.MAIN_CONFIG, *dict.fromkeys(needed_classes)]
        attrs: dict[str, list[bytes]] = {
            schema.STD_ATTR.OBJECT_CLASS: [c.encode() for c in classes],
            schema.STD_ATTR.CN: [b"config"],
        }
        for m in mods:
            if m.op == "replace":
                attrs[m.attr] = list(m.values)
        try:
            directory.add(dn, attrs)
        except AlreadyExistsError:
            entry = directory.get(dn)
            directory.modify(dn, [*_class_mods(entry, needed_classes), *_plan(entry, validated)])
    else:
        directory.modify(dn, [*_class_mods(entry, needed_classes), *mods])
    invalidate(directory)
    return written


def _class_mods(entry: Entry | None, needed: Sequence[str]) -> list[Modification]:
    have: set[str] = {c.lower() for c in entry.texts("objectClass")} if entry is not None else set()
    missing = [c for c in dict.fromkeys(needed) if c.lower() not in have]
    return (
        [Modification("add", schema.STD_ATTR.OBJECT_CLASS, [c.encode() for c in missing])]
        if missing
        else []
    )


def describe_fields() -> list[dict[str, Any]]:
    """Static description of the knobs for the admin API."""
    return [
        {
            "key": f.key,
            "section": f.section,
            "kind": f.kind,
            "honoured": f.honoured,
            "options": list(f.options),
            "secret": f.secret,
            "default": f.default,
            "constraints": f.constraints(),
        }
        for f in CONFIG_FIELDS
    ]


def key_for_attr(attr: str) -> str | None:
    """Heracles key of an LDAP attribute name of the configuration entry."""
    f = _FIELDS_BY_ATTR.get(attr.lower())
    return f.key if f else None
