"""Directory connection settings.

Directories are declared in a YAML or TOML file whose path is given by the
``HERACLES_CONFIG`` environment variable::

    directories:
      - id: main
        label: Main directory
        uri: ldaps://ldap.example.org
        bind_dn: cn=admin,dc=example,dc=org
        bind_password: secret
        base_dn: dc=example,dc=org

Per-directory environment overrides use
``HERACLES_DIRECTORY_<ID>_<FIELD>`` (``<ID>`` upper-cased, ``-`` as ``_``), for
example ``HERACLES_DIRECTORY_MAIN_BIND_PASSWORD``. Without a config file, a
single directory called ``default`` can be defined purely through
``HERACLES_LDAP_URI``, ``HERACLES_LDAP_BASE_DN``, ``HERACLES_LDAP_BIND_DN``,
``HERACLES_LDAP_BIND_PASSWORD`` and friends.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_ENV = "HERACLES_CONFIG"
_FIELDS = ("label", "uri", "bind_dn", "bind_password", "base_dn", "starttls", "ca_file", "timeout")


class ConfigError(ValueError):
    """The configuration file is unreadable or invalid."""


class DirectoryConfig(BaseModel):
    """Connection parameters of one managed directory."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    label: str = ""
    uri: str
    bind_dn: str = ""
    bind_password: SecretStr = SecretStr("")
    base_dn: str
    starttls: bool = False
    ca_file: str | None = None
    timeout: float = Field(default=10.0, gt=0)


class LdapSettings(BaseSettings):
    """All configured directories."""

    model_config = SettingsConfigDict(env_prefix="HERACLES_LDAP_SETTINGS_", extra="ignore")

    directories: list[DirectoryConfig] = Field(default_factory=lambda: [])

    def get(self, directory_id: str) -> DirectoryConfig:
        """Return the directory with ``directory_id`` or raise ``KeyError``."""
        for d in self.directories:
            if d.id == directory_id:
                return d
        raise KeyError(directory_id)


def _read_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        if path.suffix.lower() == ".toml":
            data: object = tomllib.loads(raw.decode("utf-8"))
        elif path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(raw)
        else:
            raise ConfigError(f"unsupported config format: {path.suffix!r} (use .yaml/.yml/.toml)")
    except (tomllib.TOMLDecodeError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ConfigError(f"invalid config file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"config file {path} must contain a mapping")
    return cast("dict[str, Any]", data)


def _env_key(directory_id: str) -> str:
    return directory_id.upper().replace("-", "_").replace(".", "_")


def _apply_env(items: list[dict[str, Any]], env: Mapping[str, str]) -> None:
    for item in items:
        prefix = f"HERACLES_DIRECTORY_{_env_key(str(item.get('id', '')))}_"
        for field in _FIELDS:
            value = env.get(prefix + field.upper())
            if value is not None:
                item[field] = value


def load_settings(
    path: str | os.PathLike[str] | None = None, environ: Mapping[str, str] | None = None
) -> LdapSettings:
    """Load directory settings from file and environment.

    ``path`` defaults to ``$HERACLES_CONFIG``.
    """
    env = os.environ if environ is None else environ
    config_path = path if path is not None else env.get(CONFIG_ENV)
    items: list[dict[str, Any]] = []
    if config_path:
        data = _read_file(Path(config_path))
        raw_items = data.get("directories", [])
        if not isinstance(raw_items, list):
            raise ConfigError("'directories' must be a list")
        for raw in cast("list[object]", raw_items):
            if not isinstance(raw, dict):
                raise ConfigError("each directory must be a mapping")
            items.append(dict(cast("dict[str, Any]", raw)))
    elif env.get("HERACLES_LDAP_URI"):
        single: dict[str, Any] = {"id": "default"}
        for field in _FIELDS:
            value = env.get(f"HERACLES_LDAP_{field.upper()}")
            if value is not None:
                single[field] = value
        items.append(single)
    _apply_env(items, env)
    ids = [str(i.get("id")) for i in items]
    if len(set(ids)) != len(ids):
        raise ConfigError("duplicate directory ids")
    try:
        return LdapSettings(directories=[DirectoryConfig.model_validate(i) for i in items])
    except ValueError as exc:
        raise ConfigError(f"invalid directory configuration: {exc}") from exc
