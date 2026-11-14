"""Declarative object model: :class:`ObjectType`, :class:`Tab`, :class:`Section`.

Types are declared with class attributes; nested :class:`Tab` subclasses become
the ordered tabs of the type and :class:`Section` attributes of a tab become its
ordered sections::

    class User(ObjectType):
        name = "user"
        ...

        class Main(Tab):
            name = "main"
            object_classes = ("inetOrgPerson",)
            identity = Section("Identity", StringAttr("sn", "Last name"))
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from heracles.attributes import JSON, AnyAttribute, attribute_key, help_key, section_key, tab_key

if TYPE_CHECKING:
    from heracles.objects.hooks import TabContext


class Section:
    """An ordered, labelled group of attributes. Its name is the class attribute name."""

    def __init__(self, label: str, *attributes: AnyAttribute) -> None:
        self.label = label
        self.attributes: tuple[AnyAttribute, ...] = attributes
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def describe(self, type_name: str, tab_name: str) -> dict[str, JSON]:
        """Section part of the ``TypeDescriptor``."""
        return {
            "name": self.name,
            "label": self.label,
            "label_key": section_key(type_name, tab_name, self.name),
            "attributes": [a.describe(attribute_key(type_name, a.name)) for a in self.attributes],
        }


class Tab:
    """A group of sections mapped to objectClasses.

    The first tab of a type is its main tab (always active). ``optional`` tabs
    are active iff all their ``object_classes`` are on the entry; deactivating
    one removes those classes and every stored attribute the tab owns.
    ``requires`` lists names of other tabs that must be active.
    """

    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    #: One-line explanation shown when the tab is offered as an optional capability.
    description: ClassVar[str] = ""
    object_classes: ClassVar[Sequence[str]] = ()
    optional: ClassVar[bool] = False
    requires: ClassVar[Sequence[str]] = ()
    #: ACL key of the tab inside its type's ACL category (defaults to ``name``).
    acl_key: ClassVar[str] = ""
    #: Attributes that must be unique per object (cleared when the object is copied).
    unique_attributes: ClassVar[Sequence[str]] = ()
    sections: ClassVar[tuple[Section, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        found: dict[str, Section] = {}
        for klass in reversed(cls.__mro__):
            for key, value in vars(klass).items():
                if isinstance(value, Section):
                    found[key] = value
        cls.sections = tuple(found.values())
        if cls.name and cls.optional and not cls.object_classes:
            raise TypeError(f"optional tab {cls.name!r} must declare object_classes")

    @classmethod
    def display_label(cls) -> str:
        """The tab label (defaults to the capitalised name)."""
        return cls.label or cls.name.replace("_", " ").capitalize()

    @classmethod
    def attributes(cls) -> list[AnyAttribute]:
        """All attributes of the tab, in declaration order."""
        return [a for s in cls.sections for a in s.attributes]

    @classmethod
    def attribute(cls, name: str) -> AnyAttribute | None:
        """Attribute by name, or ``None``."""
        for attr in cls.attributes():
            if attr.name == name:
                return attr
        return None

    @classmethod
    def compute(cls, values: dict[str, Any]) -> None:
        """Hook to derive values from others (mutates ``values``). Default: nothing."""

    # Directory-aware hooks (see heracles.objects.hooks.TabContext). Default: nothing.

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        """Fill virtual attributes after the entry was read."""

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        """Adjust values before compute/validation (may report ``ctx.error``)."""

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        """Side effects on other entries once the object was written."""

    @classmethod
    def on_deactivate(cls, ctx: TabContext) -> None:
        """Side effects once the tab was removed from the object."""

    @classmethod
    def before_delete(cls, ctx: TabContext) -> None:
        """Called before the object is deleted (tab active)."""

    @classmethod
    def after_delete(cls, ctx: TabContext) -> None:
        """Called after the object was deleted (tab was active)."""

    @classmethod
    def describe(cls, type_name: str) -> dict[str, JSON]:
        """Tab part of the ``TypeDescriptor``."""
        key = tab_key(type_name, cls.name)
        out: dict[str, JSON] = {
            "name": cls.name,
            "label": cls.display_label(),
            "label_key": key,
            "optional": cls.optional,
            "description": cls.description,
            "sections": [s.describe(type_name, cls.name) for s in cls.sections],
        }
        if cls.description:
            out["description_key"] = help_key(key)
        return out


@dataclass(frozen=True, slots=True)
class Reference:
    """An attribute of another type that holds the DN of objects of this type."""

    type_name: str
    attr: str


class ObjectType:
    """Declarative object type; subclass and fill the class attributes."""

    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    label_plural: ClassVar[str] = ""
    icon: ClassVar[str] = "file"
    category: ClassVar[str] = "directory"
    # --- navigation metadata (sidebar) ---
    #: ``primary`` types get a sidebar link, ``secondary`` ones sit under the group's
    #: "More" disclosure, ``hidden`` ones are only reachable from the command palette.
    nav: ClassVar[Literal["primary", "secondary", "hidden"]] = "secondary"
    #: Sidebar group (people, organization, access, infrastructure, mail, activity,
    #: settings); ``None`` derives it from ``category``.
    nav_group: ClassVar[str | None] = None
    #: Dashboard card key whose value is shown as the type's count.
    count_key: ClassVar[str | None] = None
    # --- end navigation metadata ---
    #: objectClasses the directory schema must know for a plugin type to be
    #: registered (default: the main tab's objectClasses).
    required_object_classes: ClassVar[Sequence[str]] = ()
    #: ACL category of the type (defaults to ``name``); ACL object keys are
    #: ``<acl_category>/<tab acl_key>`` and must match existing directory data.
    acl_category: ClassVar[str] = ""
    filter: ClassVar[str] = "(objectClass=*)"
    main_attr: ClassVar[str] = ""
    name_attr: ClassVar[str] = ""
    rdn: ClassVar[str] = ""
    """Container RDN relative to a department (e.g. ``ou=people``); may be empty."""
    columns: ClassVar[Sequence[str]] = ()
    search_attrs: ClassVar[Sequence[str]] = ()
    references: ClassVar[Sequence[Reference]] = ()
    #: Capability flags: types written by Heracles itself turn these off. The
    #: object service refuses the operation and the descriptor tells the UI.
    creatable: ClassVar[bool] = True
    editable: ClassVar[bool] = True
    deletable: ClassVar[bool] = True
    tabs: ClassVar[tuple[type[Tab], ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        found: dict[str, type[Tab]] = {}
        for klass in reversed(cls.__mro__):
            for key, value in vars(klass).items():
                if isinstance(value, type) and issubclass(value, Tab):
                    found[key] = value
        cls.tabs = tuple(found.values())
        if cls.name and not cls.tabs:
            raise TypeError(f"object type {cls.name!r} declares no tab")
        if cls.name and cls.tabs[0].optional:
            raise TypeError(f"the main tab of {cls.name!r} cannot be optional")
