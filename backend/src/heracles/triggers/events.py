"""Object lifecycle hooks that run the configured triggers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from heracles.core.config_store import effective_settings
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Modification
from heracles.objects.errors import ObjectValidationError
from heracles.objects.policy import EventContext, NullEvents
from heracles.objects.state import ObjectState
from heracles.schema import legacy
from heracles.triggers.hooks import HookResult, TabHook, parse_hooks, run_hook

log = structlog.get_logger(__name__)

_CALLER_ATTRS = {
    "callerCN": "cn",
    "callerUID": "uid",
    "callerSN": "sn",
    "callerGIVENNAME": "givenName",
    "callerMAIL": "mail",
}


def _texts(raw: Mapping[str, Sequence[bytes]]) -> dict[str, list[str]]:
    return {k: [v.decode("utf-8", "replace") for v in vals] for k, vals in raw.items()}


def apply_changes(
    raw: Mapping[str, Sequence[bytes]], changes: Sequence[Modification]
) -> dict[str, list[bytes]]:
    """Attributes after applying ``changes`` to ``raw`` (used for ``premodify`` / ``check``)."""
    out: dict[str, list[bytes]] = {k: list(v) for k, v in raw.items()}
    for change in changes:
        key = next((k for k in out if k.lower() == change.attr.lower()), change.attr)
        if change.op == "replace":
            out[key] = list(change.values)
        elif change.op == "add":
            out[key] = [*out.get(key, []), *change.values]
        elif change.values:
            out[key] = [v for v in out.get(key, []) if v not in change.values]
        else:
            out.pop(key, None)
        if key in out and not out[key]:
            del out[key]
    return out


def active_tab_keys(state: ObjectState | None, registry: Any | None) -> set[str]:
    """ACL keys (``user``, ``posixAccount``, ...) of the tabs active on ``state``."""
    if state is None:
        return set()
    keys: set[str] = set()
    info = None
    if registry is not None:
        try:
            info = registry.get(state.type_name)
        except Exception:  # unknown type: fall back to tab names
            info = None
    if info is not None:
        for tab in info.tabs:
            tab_state = state.tabs.get(tab.name)
            if tab_state is not None and tab_state.active:
                keys.add(tab.acl_key or tab.name)
        return keys
    for name, tab_state in state.tabs.items():
        if tab_state.active:
            keys.add(name)
            if name == "main":
                keys.add(state.type_name)
    return keys


@dataclass(slots=True)
class TriggerSettings:
    """Settings object of the plugin hosting the trigger events."""

    #: Type registry, filled by the admin API (needed to map tabs to ACL keys).
    registry: Any = None
    #: Identifier of the directory handed to commands as ``%location%``.
    location: str = "main"
    timeout: float = 30.0


@dataclass(slots=True)
class TriggerEvents(NullEvents):
    """``ObjectEvents`` running the triggers stored in the configuration entry.

    ``pre*`` and ``check`` triggers abort the operation when the command fails (the
    command output becomes the error); ``post*`` failures are only collected as
    warnings. Successful output is kept in :attr:`messages` when the configuration
    asks for it.
    """

    directory: DirectoryClient
    caller_dn: str
    settings: TriggerSettings = field(default_factory=TriggerSettings)
    warnings: list[str] = field(default_factory=lambda: [])
    messages: list[str] = field(default_factory=lambda: [])

    # -- infrastructure ----------------------------------------------------

    def _hooks(self, mode: str, keys: set[str]) -> list[TabHook]:
        try:
            config = effective_settings(self.directory)
        except Exception:  # a broken configuration must never block the object layer
            return []
        wanted = {k.lower() for k in keys}
        return [
            h
            for h in parse_hooks(config.tab_hooks)
            if h.enabled and h.mode == mode and h.tab.lower() in wanted
        ]

    def _caller(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"callerDN": [self.caller_dn]}
        try:
            entry = self.directory.get(self.caller_dn)
        except DirectoryError:
            entry = None
        for var, attr in _CALLER_ATTRS.items():
            out[var] = entry.texts(attr)[:1] if entry is not None else []
        return out

    def _base_of(self, dn: str) -> str:
        parent = dnlib.parent(dn)
        while parent is not None:
            try:
                entry = self.directory.get(parent, ["objectClass"])
            except DirectoryError:
                entry = None
            if entry is not None and entry.has_object_class(legacy.OC.DEPARTMENT):
                return parent
            parent = dnlib.parent(parent)
        return self.directory.base_dn

    def fire(
        self,
        mode: str,
        *,
        dn: str,
        state: ObjectState | None,
        raw: Mapping[str, Sequence[bytes]],
        abort: bool,
    ) -> list[HookResult]:
        """Run the triggers of ``mode`` for the active tabs of ``state``.

        Raises :class:`ObjectValidationError` on the first failure when ``abort``.
        """
        hooks = self._hooks(mode, active_tab_keys(state, self.settings.registry))
        if not hooks:
            return []
        attrs: dict[str, Sequence[str] | str] = dict(_texts(raw))
        attrs.update(self._caller())
        attrs.update({"dn": dn, "base": self._base_of(dn), "location": self.settings.location})
        show = bool(effective_settings(self.directory).display_hook_output)
        results: list[HookResult] = []
        for hook in hooks:
            result = run_hook(hook, attrs, timeout=self.settings.timeout)
            results.append(result)
            if result.ok:
                if show and result.output:
                    self.messages.append(result.output)
                continue
            text = result.output or f"Trigger {hook.mode} on {hook.tab} failed."
            if abort:
                raise ObjectValidationError({"_": text})
            self.warnings.append(text)
        return results

    # -- ObjectEvents ------------------------------------------------------

    def pre_create(self, ctx: EventContext) -> None:
        raw = ctx.after.raw if ctx.after is not None else {}
        self.fire("check", dn=ctx.dn, state=ctx.after, raw=raw, abort=True)
        self.fire("precreate", dn=ctx.dn, state=ctx.after, raw=raw, abort=True)

    def post_create(self, ctx: EventContext) -> None:
        raw = ctx.after.raw if ctx.after is not None else {}
        self.fire("postcreate", dn=ctx.dn, state=ctx.after, raw=raw, abort=False)

    def pre_modify(self, ctx: EventContext) -> None:
        base_raw = ctx.before.raw if ctx.before is not None else {}
        raw = apply_changes(base_raw, ctx.changes)
        self.fire("check", dn=ctx.dn, state=ctx.after, raw=raw, abort=True)
        self.fire("premodify", dn=ctx.dn, state=ctx.after, raw=raw, abort=True)

    def post_modify(self, ctx: EventContext) -> None:
        raw = ctx.after.raw if ctx.after is not None else {}
        self.fire("postmodify", dn=ctx.dn, state=ctx.after, raw=raw, abort=False)

    def pre_delete(self, ctx: EventContext) -> None:
        raw = ctx.before.raw if ctx.before is not None else {}
        self.fire("preremove", dn=ctx.dn, state=ctx.before, raw=raw, abort=True)

    def post_delete(self, ctx: EventContext) -> None:
        raw = ctx.before.raw if ctx.before is not None else {}
        self.fire("postremove", dn=ctx.dn, state=ctx.before, raw=raw, abort=False)

    # -- edit locks (not raised by the object layer yet) -------------------

    def pre_lock(self, ctx: EventContext) -> None:
        self.fire("prelock", dn=ctx.dn, state=ctx.before, raw=_raw(ctx), abort=True)

    def post_lock(self, ctx: EventContext) -> None:
        self.fire("postlock", dn=ctx.dn, state=ctx.before, raw=_raw(ctx), abort=False)

    def pre_unlock(self, ctx: EventContext) -> None:
        self.fire("preunlock", dn=ctx.dn, state=ctx.before, raw=_raw(ctx), abort=True)

    def post_unlock(self, ctx: EventContext) -> None:
        self.fire("postunlock", dn=ctx.dn, state=ctx.before, raw=_raw(ctx), abort=False)


def _raw(ctx: EventContext) -> Mapping[str, Sequence[bytes]]:
    return ctx.before.raw if ctx.before is not None else {}
