"""Trigger definitions (commands run on object events) and their execution.

A trigger is stored as ``<tab key>|<mode>|<script>`` where the script may start with
``#`` to mark the trigger as deactivated. The script is the bare file name of an executable
inside the approved scripts directory of the YAML settings (``triggers.scripts_dir``). It is
executed directly, never through a shell, and receives the object attributes as environment
variables (``HRC_ATTR_<NAME>``, multiple values joined with a line feed): attribute values
are never interpolated into a command line. A stored trigger that is not a bare approved
script name is refused when it should run.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import structlog

log = structlog.get_logger(__name__)

HOOK_MODES: Final = (
    "postcreate",
    "postremove",
    "postmodify",
    "precreate",
    "preremove",
    "premodify",
    "check",
    "prelock",
    "postlock",
    "preunlock",
    "postunlock",
)
"""Modes a trigger can be attached to."""

#: Longest script name accepted from the console.
MAX_COMMAND_LENGTH: Final = 128

DEFAULT_TIMEOUT: Final = 30.0
MAX_OUTPUT: Final = 4000
MASK: Final = "********"
#: Environment of the commands: nothing of the server's own (secrets, bind credentials).
SAFE_ENV: Final = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
}

#: A script is named by a bare file name: no separator, no leading dot or dash, no shell text.
SCRIPT_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SENSITIVE = re.compile(
    r"password|passwd|secret|token|pin$|hash|principalkey|privatekey|keyvalue|salt"
    r"|radiuscontrolattribute",
    re.IGNORECASE,
)
#: An attribute whose joined value is larger is not handed over (photos, certificates...).
MAX_ATTR_ENV = 16384


@dataclass(frozen=True, slots=True)
class TabHook:
    """One trigger."""

    tab: str
    mode: str
    command: str
    enabled: bool = True

    def serialise(self) -> str:
        return f"{self.tab}|{self.mode}|{'' if self.enabled else '#'}{self.command}"


def parse_hook(value: str) -> TabHook | None:
    """Parse a stored trigger; malformed values and unknown modes yield ``None``."""
    parts = value.split("|", 2)
    if len(parts) != 3:
        return None
    tab, mode, command = (p.strip() if i < 2 else p for i, p in enumerate(parts))
    if not tab or mode not in HOOK_MODES:
        return None
    enabled = not command.lstrip().startswith("#")
    if not enabled:
        command = command.lstrip()[1:]
    if not command.strip():
        return None
    return TabHook(tab, mode, command, enabled)


def check_hook_fields(tab: str, mode: str, command: str) -> dict[str, str]:
    """Problems of a trigger typed in the console: ``{field: English message}`` (empty = valid).

    The command is the bare name of a script (see :func:`resolve_script`); the tab key may not
    contain the field separator or a line break.
    Whether the tab exists is the caller's concern (it needs the type registry).
    """
    errors: dict[str, str] = {}
    key = tab.strip()
    if not key:
        errors["tab"] = "A tab is required."
    elif any(ch in key for ch in "|\r\n\x00"):
        errors["tab"] = "Invalid tab."
    if mode not in HOOK_MODES:
        errors["mode"] = "Unknown mode."
    text = command.strip()
    if not text:
        errors["command"] = "A script is required."
    elif len(text) > MAX_COMMAND_LENGTH:
        errors["command"] = f"At most {MAX_COMMAND_LENGTH} characters."
    elif not SCRIPT_NAME.fullmatch(text):
        errors["command"] = "Give the bare file name of an approved script."
    return errors


def parse_hooks(values: Sequence[str]) -> list[TabHook]:
    return [h for h in (parse_hook(v) for v in values) if h is not None]


def mask_attrs(attrs: Mapping[str, Sequence[str] | str]) -> dict[str, Sequence[str] | str]:
    """Copy of ``attrs`` whose sensitive values (passwords, secrets, ...) are masked."""
    return {k: ([MASK] if _SENSITIVE.search(k) else v) for k, v in attrs.items()}


def resolve_script(scripts_dir: Path | None, name: str) -> Path | None:
    """The approved executable called ``name``, or ``None`` when it is not one.

    ``name`` must be a bare file name; the resolved real path (symbolic links followed) must be
    a regular executable file directly inside the real path of ``scripts_dir``.
    """
    if scripts_dir is None or not SCRIPT_NAME.fullmatch(name):
        return None
    try:
        root = scripts_dir.resolve(strict=True)
        target = (root / name).resolve(strict=True)
    except OSError:
        return None
    if target.parent != root or not target.is_file() or not os.access(target, os.X_OK):
        return None
    return target


def available_scripts(scripts_dir: Path | None) -> list[str]:
    """Names of the approved scripts currently usable in ``scripts_dir``."""
    if scripts_dir is None:
        return []
    try:
        names = sorted(p.name for p in scripts_dir.iterdir())
    except OSError:
        return []
    return [n for n in names if resolve_script(scripts_dir, n) is not None]


def script_environment(hook: TabHook, attrs: Mapping[str, Sequence[str] | str]) -> dict[str, str]:
    """Environment of a script: the safe base plus one ``HRC_ATTR_<NAME>`` per attribute.

    Secrets are masked first; names are upper-cased with every other character as ``_``.
    """
    env = dict(SAFE_ENV)
    env["HRC_TAB"] = hook.tab
    env["HRC_MODE"] = hook.mode
    for name, value in mask_attrs(attrs).items():
        values = [value] if isinstance(value, str) else list(value)
        text = "\n".join(values).replace("\x00", "")
        key = "HRC_ATTR_" + re.sub(r"[^A-Z0-9]", "_", name.upper())
        if len(text) <= MAX_ATTR_ENV:
            env.setdefault(key, text)
    return env


@dataclass(frozen=True, slots=True)
class HookResult:
    hook: TabHook
    exit_code: int | None
    output: str
    timed_out: bool = False
    #: The trigger was not run because its script is not an approved one.
    refused: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_hook(
    hook: TabHook,
    attrs: Mapping[str, Sequence[str] | str],
    *,
    scripts_dir: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HookResult:
    """Run one trigger; never raises for a failing command.

    Only a bare script name found in ``scripts_dir`` runs; anything else is refused (and the
    refusal logged) without starting a process.
    """
    script = resolve_script(scripts_dir, hook.command.strip())
    if script is None:
        log.warning(
            "trigger_refused", tab=hook.tab, mode=hook.mode, configured=scripts_dir is not None
        )
        return HookResult(
            hook, None, "The trigger is not an approved script and was not run.", refused=True
        )
    log.info("trigger_run", tab=hook.tab, mode=hook.mode)
    try:
        proc = subprocess.Popen(  # noqa: S603
            [str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",  # a command printing other bytes must not fail the operation
            env=script_environment(hook, attrs),
            cwd=script.parent,
            start_new_session=True,
        )
    except OSError as exc:
        return HookResult(hook, None, f"The command could not be started: {exc.strerror}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole process group: a grandchild holding the pipes must not outlive the run.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=2)
        log.warning("trigger_timeout", tab=hook.tab, mode=hook.mode)
        return HookResult(hook, None, "The command timed out.", timed_out=True)
    done = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    output = ((done.stdout or "") + (done.stderr or "")).strip()[:MAX_OUTPUT]
    if done.returncode != 0:
        log.warning("trigger_failed", tab=hook.tab, mode=hook.mode, code=done.returncode)
    return HookResult(hook, done.returncode, output)
