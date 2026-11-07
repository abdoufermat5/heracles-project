"""Assemble the full Heracles application (directories, domain services, routers).

* ``build_app(config_path)`` — production: directories from the config file.
* ``build_demo_app()`` — in-memory demo directory, no LDAP server needed.

Config file (YAML/TOML, path in ``$HERACLES_CONFIG``)::

    directories:            # see heracles.ldap.config
      - id: main
        uri: ldaps://ldap.example.com
        ...
    api:                    # see heracles.api.settings.ApiSettings
      admin_dns: ["uid=admin,ou=people,dc=example,dc=com"]
      static_dir: /srv/heracles/frontend
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import FastAPI

from heracles.api.app import create_app
from heracles.api.domain import Domain, install_domain
from heracles.api.settings import ApiSettings
from heracles.api.v2 import directory as directory_routes
from heracles.api.v2 import objects as object_routes
from heracles.attributes import set_default_password_checker, set_default_password_hasher
from heracles.auth.sessions import Session
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient
from heracles.ldap.config import load_settings
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.objects.registry import PluginRouterContext

__all__ = ["build_app", "build_demo_app", "create_full_app"]


def create_full_app(
    settings: ApiSettings,
    directories: dict[str, DirectoryClient],
    *,
    registry: TypeRegistry | None = None,
    load_plugins: bool = True,
) -> FastAPI:
    """Wire domain services and object routers on top of :func:`create_app`."""
    if registry is None:
        registry = TypeRegistry()
        register_builtin_types(registry)
        if load_plugins and directories:
            registry.load_plugins(next(iter(directories.values())))

    domain = Domain(
        registry=registry, admin_dns=frozenset(dnlib.normalize(d) for d in settings.admin_dns)
    )

    def is_admin(_directory: DirectoryClient, user_dn: str) -> bool:
        return domain.is_admin(user_dn)

    def release_locks(session: Session) -> None:
        directory = directories.get(session.directory_id)
        if directory is not None:
            domain.locks(session.directory_id, directory).release_all_for_user(session.user_dn)

    public = [
        factory(PluginRouterContext(directories, registry.settings.get(name)))
        for name, factory in registry.public_router_factories
    ]
    plugin_api = [
        factory(PluginRouterContext(directories, registry.settings.get(name)))
        for name, factory in registry.api_router_factories
    ]
    app = create_app(
        settings,
        directories,
        is_admin=is_admin,
        logout_hooks=[release_locks],
        extra_routers=[object_routes.router, directory_routes.router, *plugin_api],
        public_routers=public,
    )
    install_domain(app, domain)

    policy = app.state.heracles.policy

    def hash_password(plaintext: str, /) -> str:
        return policy.hash_new(plaintext)

    set_default_password_hasher(hash_password)
    set_default_password_checker(policy.problems)
    return app


def _read_config(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        return tomllib.loads(text)
    loaded: object = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: top-level mapping expected")
    return cast("dict[str, Any]", loaded)


def build_app(config_path: str | os.PathLike[str] | None = None) -> FastAPI:
    """Production application from the configuration file."""
    from heracles.ldap.pyldap import PyLdapDirectory

    path_text = config_path or os.environ.get("HERACLES_CONFIG")
    ldap_settings = load_settings(path_text)
    raw: Mapping[str, Any] = _read_config(Path(path_text)) if path_text else {}
    api_settings = ApiSettings.model_validate(raw.get("api", {}))
    directories: dict[str, DirectoryClient] = {
        cfg.id: PyLdapDirectory(cfg) for cfg in ldap_settings.directories
    }
    if not api_settings.directory_labels:
        api_settings.directory_labels = {cfg.id: cfg.label for cfg in ldap_settings.directories}
    return create_full_app(api_settings, directories)


def build_demo_app(static_dir: str | os.PathLike[str] | None = None) -> FastAPI:
    """Application on the in-memory demo directory (login ``admin`` / ``heracles``)."""
    from heracles import demo

    settings = ApiSettings(
        admin_dns=[],
        directory_labels={"main": "Demo directory"},
        enable_docs=True,
        static_dir=Path(static_dir) if static_dir else None,
    )
    settings.session.cookie_secure = False
    return create_full_app(settings, {"main": demo.build_demo_directory()})
