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
      database:
        path: /var/lib/heracles/heracles.db   # default: $HERACLES_DATA_DIR/heracles.db
    plugins:                # optional; absent: the core profile (see heracles.objects.activation)
      enabled: [posix, ssh, sudo, mail, audit, acl_admin, ppolicy, dns, systems]
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import APIRouter, Depends, FastAPI

from heracles.api.app import create_app
from heracles.api.domain import Domain, install_domain
from heracles.api.errors import not_found
from heracles.api.settings import ApiSettings, PluginsSettings
from heracles.api.v2 import directory as directory_routes
from heracles.api.v2 import objects as object_routes
from heracles.attributes import set_default_password_checker, set_default_password_hasher
from heracles.auth.mail import Mailer, MailSettings
from heracles.auth.sessions import Session
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient
from heracles.ldap.config import load_settings
from heracles.objects import TypeRegistry
from heracles.objects.activation import LOCKED_PLUGINS, PluginManager, PluginOverrideStore
from heracles.objects.builtin import register_builtin_types
from heracles.objects.registry import PluginRouterContext, discover_plugins
from heracles.storage import Database
from heracles.tasks.syslog import configure_audit_syslog

__all__ = ["build_app", "build_demo_app", "create_full_app"]


def create_full_app(
    settings: ApiSettings,
    directories: dict[str, DirectoryClient],
    *,
    registry: TypeRegistry | None = None,
    load_plugins: bool = True,
    mailer: Mailer | None = None,
) -> FastAPI:
    """Wire domain services and object routers on top of :func:`create_app`."""
    manager: PluginManager | None = None
    if registry is None:
        if load_plugins and directories:
            database = (
                Database(settings.database.path) if settings.database.path is not None else None
            )
            manager = PluginManager(
                discover_plugins(),
                next(iter(directories.values())).schema_object_classes(),
                configured=settings.plugins.enabled,
                store=PluginOverrideStore(database),
            )
            registry = manager.build_registry()
        else:
            registry = TypeRegistry()
            register_builtin_types(registry)

    domain = Domain(
        registry=registry,
        plugins=manager,
        admin_dns=frozenset(dnlib.normalize(d) for d in settings.admin_dns),
    )

    def is_admin(_directory: DirectoryClient, user_dn: str) -> bool:
        return domain.is_admin(user_dn)

    def release_locks(session: Session) -> None:
        directory = directories.get(session.directory_id)
        if directory is not None:
            domain.locks(session.directory_id, directory).release_all_for_user(session.user_dn)

    if manager is None:
        public = [
            factory(PluginRouterContext(directories, registry.settings.get(name)))
            for name, factory in registry.public_router_factories
        ]
        plugin_api = [
            factory(PluginRouterContext(directories, registry.settings.get(name)))
            for name, factory in registry.api_router_factories
        ]
    else:
        public, plugin_api = _plugin_routers(manager, directories)
    app = create_app(
        settings,
        directories,
        mailer=mailer,
        is_admin=is_admin,
        logout_hooks=[release_locks],
        # plugin routers first: their specific paths must win over the catch-all object routes
        extra_routers=[*plugin_api, object_routes.router, directory_routes.router],
        public_routers=public,
    )
    install_domain(app, domain)

    policy = app.state.heracles.policy

    def hash_password(plaintext: str, /) -> str:
        return policy.hash_new(plaintext)

    set_default_password_hasher(hash_password)
    set_default_password_checker(policy.problems)
    return app


def _gated(manager: PluginManager, name: str, router: APIRouter) -> APIRouter:
    """``router`` answering 404 while plugin ``name`` is disabled.

    Routers are mounted once, at start-up; the gate is what makes a console toggle take
    effect without a restart. Plugins that cannot be disabled are mounted as they are.
    """
    if name in LOCKED_PLUGINS:
        return router

    def gate() -> None:
        if not manager.is_enabled(name):
            raise not_found("This feature is disabled")

    outer = APIRouter(dependencies=[Depends(gate)])
    outer.include_router(router)
    return outer


def _plugin_routers(
    manager: PluginManager, directories: dict[str, DirectoryClient]
) -> tuple[list[APIRouter], list[APIRouter]]:
    """``(public, authenticated)`` routers of every available plugin, each gated."""
    public: list[APIRouter] = []
    api: list[APIRouter] = []
    for plugin in manager.plugins:
        if not manager.is_available(plugin.name):
            continue
        ctx = PluginRouterContext(directories, plugin.settings)
        public.extend(_gated(manager, plugin.name, f(ctx)) for f in plugin.public_routers)
        api.extend(_gated(manager, plugin.name, f(ctx)) for f in plugin.api_routers)
    return public, api


def read_config(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        return tomllib.loads(text)
    loaded: object = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: top-level mapping expected")
    return cast("dict[str, Any]", loaded)


def load_config(
    config_path: str | os.PathLike[str] | None = None,
) -> tuple[Mapping[str, Any], ApiSettings, dict[str, DirectoryClient]]:
    """The raw configuration, the API settings and the directories it describes."""
    from heracles.ldap.pyldap import PyLdapDirectory

    path_text = config_path or os.environ.get("HERACLES_CONFIG")
    ldap_settings = load_settings(path_text)
    raw: Mapping[str, Any] = read_config(Path(path_text)) if path_text else {}
    api_settings = ApiSettings.model_validate(raw.get("api", {}))
    directories: dict[str, DirectoryClient] = {
        cfg.id: PyLdapDirectory(cfg) for cfg in ldap_settings.directories
    }
    if api_settings.database.path is None:
        data_dir = Path(os.environ.get("HERACLES_DATA_DIR", "/var/lib/heracles"))
        api_settings.database.path = data_dir / "heracles.db"
    if "plugins" in raw and "plugins" not in raw.get("api", {}):
        api_settings.plugins = PluginsSettings.model_validate(raw["plugins"])
    if not api_settings.directory_labels:
        api_settings.directory_labels = {cfg.id: cfg.label for cfg in ldap_settings.directories}
    return raw, api_settings, directories


def build_app(
    config_path: str | os.PathLike[str] | None = None, *, with_worker: bool | None = None
) -> FastAPI:
    """Production application from the configuration file.

    With ``with_worker`` (default: ``$HERACLES_WITH_WORKER`` is set) the task scheduler runs
    in a background thread of this process.
    """
    from heracles.tasks.wiring import attach_scheduler

    raw, api_settings, directories = load_config(config_path)
    mailer = MailSettings.model_validate(raw.get("mail") or {}).build()
    configure_audit_syslog(raw.get("audit"))
    app = create_full_app(api_settings, directories, mailer=mailer)
    if with_worker is None:
        with_worker = bool(os.environ.get("HERACLES_WITH_WORKER"))
    if with_worker:
        interval = float(os.environ.get("HERACLES_WORKER_INTERVAL", "60"))
        attach_scheduler(app, mailer=mailer, interval=interval, start=True)
    return app


def build_demo_app(static_dir: str | os.PathLike[str] | None = None) -> FastAPI:
    """Application on the in-memory demo directory (login ``admin`` / ``heracles``)."""
    from heracles import demo

    settings = ApiSettings(
        admin_dns=[],
        directory_labels={"main": "Demo directory"},
        enable_docs=True,
        static_dir=Path(static_dir) if static_dir else None,
        plugins=PluginsSettings(enabled=["*"]),  # the demo shows every extension
    )
    settings.session.cookie_secure = False
    return create_full_app(settings, {"main": demo.build_demo_directory()})
