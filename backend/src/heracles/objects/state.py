"""In-memory representation of a loaded object."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from heracles.attributes import JSON
from heracles.objects.model import Tab


@dataclass(slots=True)
class TabState:
    """Whether a tab is active and its typed values (by attribute name)."""

    active: bool = False
    values: dict[str, Any] = field(default_factory=lambda: {})


@dataclass(slots=True)
class ObjectState:
    """A loaded object: per-tab state plus the original state used for diffing."""

    dn: str
    type_name: str
    tabs: dict[str, TabState]
    original: dict[str, TabState]
    raw: dict[str, list[bytes]] = field(default_factory=lambda: {})
    """Raw LDAP attributes of the entry at load time."""
    object_classes: list[str] = field(default_factory=lambda: [])

    @classmethod
    def build(
        cls,
        dn: str,
        type_name: str,
        tabs: dict[str, TabState],
        raw: dict[str, list[bytes]],
        object_classes: list[str],
    ) -> ObjectState:
        """Create a state whose ``original`` is a deep copy of ``tabs``."""
        return cls(dn, type_name, tabs, copy.deepcopy(tabs), raw, object_classes)

    def to_json(self, tab_classes: list[type[Tab]]) -> dict[str, JSON]:
        """JSON form of ``GET /objects/{type}/{dn}`` (without the ``acl`` part)."""
        tabs: dict[str, JSON] = {}
        for tab in tab_classes:
            state = self.tabs.get(tab.name, TabState())
            values: dict[str, JSON] = {}
            if state.active:
                for attr in tab.attributes():
                    if attr.name in state.values:
                        values[attr.name] = attr.to_json(state.values.get(attr.name))
            tabs[tab.name] = {"active": state.active, "values": values}
        return {"dn": self.dn, "type": self.type_name, "tabs": tabs}
