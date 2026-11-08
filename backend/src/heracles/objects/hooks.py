"""Context handed to tab hooks (``on_load``, ``prepare``, ``after_save``, ...).

Hooks let plugin tabs compute values that need the directory (id allocation,
virtual attributes backed by other entries) and apply side effects on other
entries after a save.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from heracles.ldap.client import DirectoryClient
from heracles.objects.policy import TypedPolicy

if TYPE_CHECKING:
    from heracles.objects.policy import AccessPolicy
    from heracles.objects.registry import TypeInfo, TypeRegistry
    from heracles.objects.state import TabState


@dataclass(slots=True)
class TabContext:
    """What a tab hook can see and change."""

    directory: DirectoryClient
    registry: TypeRegistry
    info: TypeInfo
    tab_name: str
    #: DN of the object (``None`` in ``prepare`` during creation).
    dn: str | None
    #: Department DN the object lives in.
    base: str
    creating: bool
    #: The tab is being activated by this change (or the object created).
    activating: bool
    #: Mutable values of this tab.
    values: dict[str, Any]
    #: Every tab state (new values).
    tabs: Mapping[str, TabState]
    #: Tab states before the change (``None`` on creation).
    original: Mapping[str, TabState] | None = None
    #: ``(tab, attribute)`` pairs set by the request.
    touched: Sequence[tuple[str, str]] = ()
    #: Field errors (``"tab.attr"`` → message) collected during ``prepare``.
    errors: dict[str, str] = field(default_factory=lambda: {})
    #: Access policy of the acting user (``None``: everything is allowed).
    policy: AccessPolicy | None = None

    def can_write_object(self, type_name: str, dn: str, tab: str, attr: str) -> bool:
        """True if the acting user may write ``tab.attr`` of ``dn``, an object of another type."""
        policy = self.policy
        if policy is None:
            return True
        if isinstance(policy, TypedPolicy):
            policy = policy.for_type(type_name)
        return policy.can_write(dn, tab, attr)

    @property
    def settings(self) -> Mapping[str, Any]:
        """Plugin settings registered on the registry (plugin name → settings)."""
        return self.registry.settings

    def main_values(self) -> dict[str, Any]:
        """Values of the type's main tab."""
        return self.tabs[self.info.main_tab.name].values

    def original_values(self) -> dict[str, Any]:
        """Values of this tab before the change (empty when it was inactive)."""
        if self.original is None:
            return {}
        state = self.original.get(self.tab_name)
        return state.values if state is not None and state.active else {}

    def was_touched(self, attr: str, tab: str | None = None) -> bool:
        """True if the request set ``attr`` of ``tab`` (default: this tab)."""
        wanted = tab or self.tab_name
        return any(t == wanted and a == attr for t, a in self.touched)

    def error(self, attr: str, message: str) -> None:
        """Report a field error on an attribute of this tab."""
        self.errors.setdefault(f"{self.tab_name}.{attr}", message)
