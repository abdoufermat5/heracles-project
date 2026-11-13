"""Which plugins are on: operator choice on top of schema availability.

A plugin is *available* when the directory schema defines its objectClasses and
*enabled* when the operator turned it on. The enabled set is, in increasing order of
precedence:

1. the default core profile (:data:`CORE_PROFILE`), or the ``plugins.enabled`` list of the
   configuration file when it is present;
2. the overrides an administrator set from the console, kept in the application database;
3. :data:`LOCKED_PLUGINS`, which cannot be turned off (the console itself).

:class:`PluginManager` owns that decision and rebuilds the :class:`TypeRegistry` when it
changes, so a toggle takes effect without a restart.
"""

from __future__ import annotations

import threading
from collections.abc import Collection, Iterable, Mapping, Sequence

import structlog

from heracles.objects.registry import Plugin, TypeRegistry
from heracles.storage import Database

__all__ = [
    "CORE_PROFILE",
    "LOCKED_PLUGINS",
    "WILDCARD",
    "PluginLockedError",
    "PluginManager",
    "PluginOverrideStore",
    "UnavailablePluginError",
    "UnknownPluginError",
]

log = structlog.get_logger(__name__)

#: Plugins on when the configuration does not list any (each only if available).
CORE_PROFILE: tuple[str, ...] = ("posix", "ssh", "sudo", "mail", "audit", "acl_admin", "ppolicy")
#: Plugins that cannot be switched off: ``acl_admin`` serves the administration API.
LOCKED_PLUGINS: frozenset[str] = frozenset({"acl_admin"})

#: In ``plugins.enabled``: every plugin the schema supports (demo, tests).
WILDCARD = "*"

COMPONENT = "plugins"

#: Append only; never edit a released migration.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE plugin_overrides (
        name TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_by TEXT NOT NULL DEFAULT ''
    );
    """,
)


class UnknownPluginError(KeyError):
    """No installed plugin has this name."""


class UnavailablePluginError(ValueError):
    """The directory schema does not define the plugin's objectClasses."""


class PluginLockedError(ValueError):
    """The plugin cannot be switched off."""


class PluginOverrideStore:
    """Administrator overrides (plugin name -> on/off); in memory without a database."""

    def __init__(self, database: Database | None = None) -> None:
        self._db = database
        self._memory: dict[str, bool] = {}
        if database is not None:
            database.migrate(COMPONENT, MIGRATIONS)

    def load(self) -> dict[str, bool]:
        if self._db is None:
            return dict(self._memory)
        with self._db.connection() as conn:
            rows = conn.execute("SELECT name, enabled FROM plugin_overrides").fetchall()
        return {str(r["name"]): bool(r["enabled"]) for r in rows}

    def set(self, name: str, enabled: bool, user: str = "") -> None:
        if self._db is None:
            self._memory[name] = enabled
            return
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO plugin_overrides (name, enabled, updated_by) VALUES (?, ?, ?)"
                " ON CONFLICT (name) DO UPDATE SET enabled = excluded.enabled,"
                " updated_at = CURRENT_TIMESTAMP, updated_by = excluded.updated_by",
                (name, int(enabled), user),
            )


class PluginManager:
    """Decides the enabled set and builds the registry from it."""

    def __init__(
        self,
        plugins: Sequence[Plugin],
        available_classes: Collection[str],
        *,
        configured: Iterable[str] | None = None,
        store: PluginOverrideStore | None = None,
        database: Database | None = None,
    ) -> None:
        self.plugins = list(plugins)
        self.available_classes = {c.lower() for c in available_classes}
        self.configured = None if configured is None else list(configured)
        self.store = store or PluginOverrideStore()
        #: Application database shared with the plugins through the registry.
        self.database = database
        #: Serialises toggles (and the registry swap that follows).
        self.lock = threading.RLock()
        #: Stored overrides the last registry was built from (see :meth:`refresh`).
        self._applied: dict[str, bool] | None = None
        known = {p.name for p in self.plugins}
        for name in [*(self.configured or ()), *self.store.load()]:
            if name not in known and name != WILDCARD:
                log.warning("plugin_unknown", plugin=name)

    def get(self, name: str) -> Plugin:
        for plugin in self.plugins:
            if plugin.name == name:
                return plugin
        raise UnknownPluginError(name)

    def is_available(self, name: str) -> bool:
        return not self.get(name).missing_object_classes(self.available_classes)

    def enabled_names(self, overrides: Mapping[str, bool] | None = None) -> set[str]:
        """Names switched on (before the schema availability filter)."""
        names = set(CORE_PROFILE if self.configured is None else self.configured)
        if WILDCARD in names:
            names |= {p.name for p in self.plugins}
        for name, on in (self.store.load() if overrides is None else overrides).items():
            if on:
                names.add(name)
            else:
                names.discard(name)
        return names | LOCKED_PLUGINS

    def is_enabled(self, name: str) -> bool:
        try:
            return name in self.enabled_names() and self.is_available(name)
        except UnknownPluginError:
            return False

    def build_registry(self) -> TypeRegistry:
        """A fresh registry: built-in types plus the enabled plugins."""
        from heracles.objects.builtin import register_builtin_types

        with self.lock:
            overrides = self.store.load()
            registry = TypeRegistry()
            registry.database = self.database
            register_builtin_types(registry)
            registry.register_plugins(
                self.plugins, self.available_classes, self.enabled_names(overrides)
            )
            self._applied = overrides
            return registry

    def refresh(self) -> TypeRegistry | None:
        """A rebuilt registry when the stored overrides changed since the last build.

        Several server processes share the app database: a plugin switched in one of them
        reaches the others through this check. ``None`` when nothing changed.
        """
        with self.lock:
            try:
                current = self.store.load()
            except Exception as exc:  # a database hiccup must not break requests
                log.warning("plugin_refresh_failed", error=type(exc).__name__)
                return None
            if current == self._applied:
                return None
            log.info("plugins_changed_elsewhere")
            return self.build_registry()

    def set_enabled(self, name: str, enabled: bool, user: str = "") -> TypeRegistry:
        """Store the override and return the rebuilt registry (the caller swaps it in)."""
        with self.lock:
            self.get(name)
            if enabled and not self.is_available(name):
                raise UnavailablePluginError(name)
            if not enabled and name in LOCKED_PLUGINS:
                raise PluginLockedError(name)
            self.store.set(name, enabled, user)
            return self.build_registry()
