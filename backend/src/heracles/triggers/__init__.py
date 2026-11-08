"""Triggers: commands run on object events (create, modify, remove, lock)."""

from heracles.triggers.events import (
    TriggerEvents,
    TriggerSettings,
    active_tab_keys,
    apply_changes,
)
from heracles.triggers.hooks import (
    HOOK_MODES,
    HookResult,
    TabHook,
    mask_attrs,
    parse_hook,
    parse_hooks,
    render_command,
    run_hook,
)

__all__ = [
    "HOOK_MODES",
    "HookResult",
    "TabHook",
    "TriggerEvents",
    "TriggerSettings",
    "active_tab_keys",
    "apply_changes",
    "mask_attrs",
    "parse_hook",
    "parse_hooks",
    "render_command",
    "run_hook",
]
