"""Type registry and plugin loading."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Protocol, cast

from heracles.attributes import JSON, AnyAttribute
from heracles.ldap.client import DirectoryClient, Entry, Modification
from heracles.objects.errors import UnknownTypeError
from heracles.objects.model import ObjectType, Tab

PLUGIN_GROUP = "heracles.plugins"


class TypeInfo:
    """A registered type together with its (possibly plugin-extended) tabs."""

    def __init__(self, type_cls: type[ObjectType]) -> None:
        self.type = type_cls
        self.tabs: list[type[Tab]] = list(type_cls.tabs)

    @property
    def name(self) -> str:
        return self.type.name

    @property
    def main_tab(self) -> type[Tab]:
        return self.tabs[0]

    @property
    def acl_category(self) -> str:
        """ACL category of the type."""
        return self.type.acl_category or self.type.name

    def acl_object(self, tab: type[Tab]) -> str:
        """ACL object key ``<category>/<tabKey>`` of one of the type's tabs."""
        return f"{self.acl_category}/{tab.acl_key or tab.name}"

    def tab(self, name: str) -> type[Tab] | None:
        """Tab class by name."""
        return next((t for t in self.tabs if t.name == name), None)

    def find_attribute(self, name: str) -> AnyAttribute | None:
        """First attribute called ``name`` in any tab."""
        for tab in self.tabs:
            attr = tab.attribute(name)
            if attr is not None:
                return attr
        return None

    def summary(self, *, can_create: bool = True) -> dict[str, JSON]:
        """``TypeSummary`` JSON."""
        return {
            "name": self.type.name,
            "label": self.type.label,
            "label_plural": self.type.label_plural or self.type.label,
            "icon": self.type.icon,
            "category": self.type.category,
            "can_create": can_create,
        }

    def describe(self) -> dict[str, JSON]:
        """``TypeDescriptor`` JSON."""
        columns: list[JSON] = []
        for key in self.type.columns:
            attr = self.find_attribute(key)
            columns.append({"key": key, "label": attr.label if attr else key})
        return {
            "name": self.type.name,
            "label": self.type.label,
            "icon": self.type.icon,
            "category": self.type.category,
            "main_attr": self.type.main_attr,
            "name_attr": self.type.name_attr,
            "columns": columns,
            "tabs": [t.describe() for t in self.tabs],
        }


#: ``hook(entry, locked) -> modifications`` run on account lock (True) / unlock (False).
type AccountLockHook = Callable[[Entry, bool], list[Modification]]


@dataclass(frozen=True, slots=True)
class TabAttachment:
    """Attach ``tab`` to the existing type called ``type_name``."""

    type_name: str
    tab: type[Tab]


@dataclass(frozen=True, slots=True)
class Plugin:
    """What a plugin entry point returns."""

    name: str
    version: str
    types: Sequence[type[ObjectType]] = ()
    tabs: Sequence[TabAttachment] = ()
    required_object_classes: Sequence[str] = ()
    #: Extra modifications applied when a user account is locked/unlocked.
    account_lock_hooks: Sequence[AccountLockHook] = ()
    #: Default settings, registered as ``registry.settings[name]`` unless already set.
    settings: Any = None
    config: Any = None
    """Optional configuration section description (opaque here)."""

    def missing_object_classes(self, available: set[str]) -> list[str]:
        """Required classes absent from ``available`` (lower-cased names)."""
        return [c for c in self.required_object_classes if c.lower() not in available]


@dataclass(frozen=True, slots=True)
class PluginStatus:
    """Outcome of loading one plugin."""

    name: str
    version: str
    enabled: bool
    missing_object_classes: list[str] = field(default_factory=lambda: [])


class EntryPointLike(Protocol):
    """The part of ``importlib.metadata.EntryPoint`` that is used."""

    name: str

    def load(self) -> Any: ...


class TypeRegistry:
    """Registered object types, in registration order."""

    def __init__(self) -> None:
        #: Plugin settings (plugin name → settings object), visible to tab hooks.
        self.settings: dict[str, Any] = {}
        #: Account lock hooks of enabled plugins.
        self.account_lock_hooks: list[AccountLockHook] = []
        self._types: dict[str, TypeInfo] = {}
        self.plugins: list[PluginStatus] = []

    def register_type(self, type_cls: type[ObjectType]) -> TypeInfo:
        """Register a type (name must be unique)."""
        if not type_cls.name:
            raise ValueError("cannot register an unnamed type")
        if type_cls.name in self._types:
            raise ValueError(f"type {type_cls.name!r} already registered")
        info = TypeInfo(type_cls)
        self._types[type_cls.name] = info
        return info

    def attach_tab(self, type_name: str, tab_cls: type[Tab]) -> None:
        """Add ``tab_cls`` to an existing type (e.g. from a plugin)."""
        info = self.get(type_name)
        if info.tab(tab_cls.name) is not None:
            raise ValueError(f"tab {tab_cls.name!r} already on type {type_name!r}")
        if not tab_cls.optional:
            raise ValueError("attached tabs must be optional")
        info.tabs.append(tab_cls)

    def get(self, name: str) -> TypeInfo:
        """Type by name; raises :class:`UnknownTypeError`."""
        try:
            return self._types[name]
        except KeyError:
            raise UnknownTypeError(name) from None

    def list(self) -> Sequence[TypeInfo]:
        """All types in registration order."""
        return [*self._types.values()]

    def describe(self, name: str) -> dict[str, JSON]:
        """``TypeDescriptor`` of one type."""
        return self.get(name).describe()

    def summaries(self, can_create: Callable[[str], bool] | None = None) -> Sequence[JSON]:
        """``TypeSummary`` list."""
        return [
            t.summary(can_create=can_create(t.name) if can_create else True) for t in self.list()
        ]

    # -- plugins -----------------------------------------------------------

    def register_plugin(self, plugin: Plugin, available_classes: set[str]) -> PluginStatus:
        """Register ``plugin`` iff its required objectClasses are all available."""
        missing = plugin.missing_object_classes(available_classes)
        status = PluginStatus(plugin.name, plugin.version, not missing, missing)
        self.plugins.append(status)
        if missing:
            return status
        for type_cls in plugin.types:
            self.register_type(type_cls)
        for att in plugin.tabs:
            self.attach_tab(att.type_name, att.tab)
        self.account_lock_hooks.extend(plugin.account_lock_hooks)
        if plugin.settings is not None:
            self.settings.setdefault(plugin.name, plugin.settings)
        return status

    def load_plugins(
        self,
        directory: DirectoryClient,
        found: Iterable[EntryPointLike] | None = None,
    ) -> Sequence[PluginStatus]:
        """Load every ``heracles.plugins`` entry point against the directory schema."""
        available = {c.lower() for c in directory.schema_object_classes()}
        points: Iterable[EntryPointLike] = (
            found if found is not None else entry_points(group=PLUGIN_GROUP)
        )
        statuses: list[PluginStatus] = []
        for point in points:
            loaded = point.load()
            plugin = cast("Plugin", loaded() if callable(loaded) else loaded)
            statuses.append(self.register_plugin(plugin, available))
        return statuses
