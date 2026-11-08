"""LDIF import: plan (dry run) and apply, entry by entry, on a raw directory client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from heracles.core import config_store
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, Modification
from heracles.schema import legacy

Action = Literal["add", "modify", "unchanged", "exists", "error"]

MAX_ENTRIES = 5000
MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """Behaviour switches of the import."""

    #: Replace the attributes of entries that already exist (otherwise they are reported).
    overwrite: bool = False
    #: With ``overwrite``: also delete the attributes that are not in the LDIF.
    remove_missing: bool = False


@dataclass(slots=True)
class EntryResult:
    """Outcome (or plan) for one LDIF record."""

    index: int
    dn: str
    action: Action
    changes: list[str] = field(default_factory=lambda: [])
    error: str | None = None


def configuration_entry(directory: DirectoryClient) -> Callable[[Entry], bool]:
    """Predicate for the entries only administrators may import.

    The configuration entry defines the triggers, i.e. commands the server runs, so
    writing it (or any entry carrying a trigger or one of its object classes) through
    a raw import is equivalent to code execution.
    """
    config_dn = dnlib.normalize(config_store.config_dn(directory))
    classes = {c.lower() for c in legacy.CONFIG_ENTRY_CLASSES}

    def check(entry: Entry) -> bool:
        if dnlib.normalize(entry.dn) == config_dn:
            return True
        names = {name.lower() for name in entry.attrs}
        if legacy.TAB_HOOK_ATTR.lower() in names:
            return True
        return any(
            value.decode("utf-8", "replace").lower() in classes
            for name, values in entry.attrs.items()
            if name.lower() == "objectclass"
            for value in values
        )

    return check


def _by_name(entry: Entry) -> dict[str, tuple[str, list[bytes]]]:
    return {name.lower(): (name, list(values)) for name, values in entry.attrs.items()}


def _modifications(current: Entry, wanted: Entry, options: ImportOptions) -> list[Modification]:
    have = _by_name(current)
    want = _by_name(wanted)
    changes: list[Modification] = []
    for key, (name, values) in want.items():
        existing = have.get(key)
        if existing is None or sorted(existing[1]) != sorted(values):
            changes.append(Modification("replace", name, values))
    if options.remove_missing:
        for key, (name, _values) in have.items():
            if key not in want:
                changes.append(Modification("delete", name))
    return changes


def _describe(exc: DirectoryError) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}"[:300] if text else type(exc).__name__


def run_import(
    directory: DirectoryClient,
    entries: list[Entry],
    options: ImportOptions,
    *,
    allowed: Callable[[str], bool],
    apply: bool,
    protected: Callable[[Entry], bool] | None = None,
) -> list[EntryResult]:
    """Process ``entries`` in order; with ``apply`` false nothing is written (dry run).

    A record whose parent is neither in the directory nor an earlier record is an error.
    Failures never stop the run: every record gets a result. ``protected`` marks the
    entries a raw import must never write (the new record, or the entry it would change).
    """
    results: list[EntryResult] = []
    planned: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        result = EntryResult(index, entry.dn, "error")
        results.append(result)
        key = dnlib.normalize(entry.dn)
        if not dnlib.split(entry.dn):
            result.error = "Invalid DN"
            continue
        if not allowed(entry.dn):
            result.error = "You are not allowed to import entries here"
            continue
        try:
            existing = directory.get(entry.dn)
            if protected is not None and (
                protected(entry) or (existing is not None and protected(existing))
            ):
                result.error = "This entry can only be changed by an administrator"
                continue
            if existing is None and key not in planned:
                _add(directory, entry, result, planned, apply=apply)
            elif key in planned and existing is None:
                result.error = "Duplicate entry in the file"
            else:
                assert existing is not None
                _update(directory, existing, entry, options, result, apply=apply)
        except DirectoryError as exc:
            result.action = "error"
            result.error = _describe(exc)
    return results


def _add(
    directory: DirectoryClient,
    entry: Entry,
    result: EntryResult,
    planned: set[str],
    *,
    apply: bool,
) -> None:
    if not _by_name(entry).get("objectclass"):
        result.error = "The entry has no objectClass"
        return
    parent = dnlib.parent(entry.dn)
    is_base = dnlib.normalize(entry.dn) == dnlib.normalize(directory.base_dn)
    if not is_base and (
        parent is None or (dnlib.normalize(parent) not in planned and directory.get(parent) is None)
    ):
        result.error = "The parent entry does not exist"
        return
    if apply:
        directory.add(entry.dn, {name: list(values) for name, values in entry.attrs.items()})
    planned.add(dnlib.normalize(entry.dn))
    result.action = "add"
    result.changes = sorted(entry.attrs, key=str.lower)


def _update(
    directory: DirectoryClient,
    existing: Entry,
    entry: Entry,
    options: ImportOptions,
    result: EntryResult,
    *,
    apply: bool,
) -> None:
    if not options.overwrite:
        result.action = "exists"
        result.error = "The entry already exists"
        return
    changes = _modifications(existing, entry, options)
    if not changes:
        result.action = "unchanged"
        return
    if apply:
        directory.modify(entry.dn, changes)
    result.action = "modify"
    result.changes = [c.attr for c in changes]


def summarize(results: list[EntryResult]) -> dict[str, int]:
    """Count of results per action."""
    out = {"add": 0, "modify": 0, "unchanged": 0, "exists": 0, "error": 0}
    for item in results:
        out[item.action] += 1
    return out
