"""Trigger definitions (commands run on object events) and their execution.

A trigger is stored as ``<tab key>|<mode>|<command>`` where the command may start
with ``#`` to mark the trigger as deactivated. Commands run through ``/bin/sh -c``
after ``%attribute%`` placeholders were replaced by shell-quoted attribute values.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import structlog

from heracles.objects.masks import (
    Literal,
    MaskEnv,
    MaskError,
    Placeholder,
    evaluate_placeholder,
    parse_mask,
)

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

DEFAULT_TIMEOUT: Final = 30.0
MAX_OUTPUT: Final = 4000
MASK: Final = "********"
#: Environment of the commands: nothing of the server's own (secrets, bind credentials).
SAFE_ENV: Final = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
}

_PLACEHOLDER = re.compile(r"%([A-Za-z][A-Za-z0-9;_-]*)%")
_SENSITIVE = re.compile(r"password|secret|token|pin$|passwd|hash", re.IGNORECASE)


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


def parse_hooks(values: Sequence[str]) -> list[TabHook]:
    return [h for h in (parse_hook(v) for v in values) if h is not None]


class _ShellContext:
    """Tracks the shell quoting state while a command is assembled.

    A value must be escaped for the place where it lands: unquoted, inside single
    quotes, inside double quotes or inside a backquoted command. A single quoting
    style would let a value break out of a placeholder written between quotes.
    """

    def __init__(self) -> None:
        self._stack: list[str] = []  # "'" | '"' | "(" (a $( ) command) | "`"
        self._pending_escape = False

    def feed(self, text: str) -> None:
        i = 0
        while i < len(text):
            ch = text[i]
            top = self._stack[-1] if self._stack else ""
            if self._pending_escape:
                self._pending_escape = False
            elif top == "'":
                if ch == "'":
                    self._stack.pop()
            elif ch == "\\":
                if i + 1 < len(text):
                    i += 1
                else:
                    self._pending_escape = True
            elif ch == "$" and text[i + 1 : i + 2] == "(":
                self._stack.append("(")
                i += 1
            elif ch == "`":
                if top == "`":
                    self._stack.pop()
                else:
                    self._stack.append("`")
            elif ch == '"':
                if top == '"':
                    self._stack.pop()
                else:
                    self._stack.append('"')
            elif ch == "'" and top != '"':
                self._stack.append("'")
            elif ch == ")" and top == "(":
                self._stack.pop()
            i += 1

    def escape(self, value: str) -> str:
        """``value`` made inert at the current position."""
        if self._pending_escape:
            return ""
        top = self._stack[-1] if self._stack else ""
        if top == "'":
            return value.replace("'", "'\\''")
        if top == '"':
            return re.sub(r'([\\"$`])', r"\\\1", value)
        if top == "`":
            return re.sub(r"[^A-Za-z0-9_@%+=:,./ -]", "", value)
        return shlex.quote(value)


def render_command(cmd: str, attrs: Mapping[str, Sequence[str] | str]) -> str:
    """Render a trigger command, escaping every substituted value for its quoting context.

    Placeholders use the syntax of the template masks
    (:mod:`heracles.objects.masks`), so ``%attr%`` and ``%modifiers|attr%`` mean the
    same thing here and in templates. A value is shell-quoted when the placeholder is
    unquoted and escaped for the enclosing quotes when it is written between single or
    double quotes. A placeholder naming an attribute the object does not have is left
    verbatim, so shell text such as ``date +%s`` keeps working. An invalid mask or a
    failed modifier becomes an empty string; a value can never inject text into the
    command line.
    """
    lowered = {k.lower(): v for k, v in attrs.items()}
    shell = _ShellContext()

    def first_of(name: str) -> str:
        value = lowered.get(name.lower())
        if value is None:
            return ""
        return value if isinstance(value, str) else (value[0] if value else "")

    if "%" not in cmd:
        return cmd
    try:
        segments = parse_mask(cmd)
    except MaskError:
        out: list[str] = []
        last = 0
        for m in _PLACEHOLDER.finditer(cmd):
            literal = cmd[last : m.start()]
            shell.feed(literal)
            out.append(literal)
            if m.group(1).lower() in lowered:
                out.append(shell.escape(first_of(m.group(1))))
            else:
                out.append(m.group(0))
                shell.feed(m.group(0))
            last = m.end()
        out.append(cmd[last:])
        return "".join(out)
    if not any(
        isinstance(s, Placeholder) and (s.modifiers or s.attr.lower() in lowered) for s in segments
    ):
        return cmd
    env = MaskEnv()
    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, Literal):
            shell.feed(segment.text)
            parts.append(segment.text)
            continue
        value = lowered.get(segment.attr.lower())
        if value is None and not segment.modifiers:
            text = f"%{segment.attr}%"
            shell.feed(text)
            parts.append(text)
            continue
        values = [] if value is None else ([value] if isinstance(value, str) else list(value))
        try:
            resolved = evaluate_placeholder(segment, values, env)
        except (MaskError, ValueError):
            resolved = []
        parts.append(shell.escape(resolved[0] if resolved else ""))
    return "".join(parts)


def mask_attrs(attrs: Mapping[str, Sequence[str] | str]) -> dict[str, Sequence[str] | str]:
    """Copy of ``attrs`` whose sensitive values (passwords, secrets, ...) are masked."""
    return {k: ([MASK] if _SENSITIVE.search(k) else v) for k, v in attrs.items()}


@dataclass(frozen=True, slots=True)
class HookResult:
    hook: TabHook
    exit_code: int | None
    output: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_hook(
    hook: TabHook, attrs: Mapping[str, Sequence[str] | str], *, timeout: float = DEFAULT_TIMEOUT
) -> HookResult:
    """Run one trigger; never raises for a failing command."""
    command = render_command(hook.command, attrs)
    logged = render_command(hook.command, mask_attrs(attrs))
    log.info("trigger_run", tab=hook.tab, mode=hook.mode, command=logged)
    try:
        proc = subprocess.Popen(  # noqa: S603
            ["/bin/sh", "-c", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(SAFE_ENV),
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
        log.warning("trigger_timeout", tab=hook.tab, mode=hook.mode, command=logged)
        return HookResult(hook, None, "The command timed out.", timed_out=True)
    done = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    output = ((done.stdout or "") + (done.stderr or "")).strip()[:MAX_OUTPUT]
    if done.returncode != 0:
        log.warning("trigger_failed", tab=hook.tab, mode=hook.mode, code=done.returncode)
    return HookResult(hook, done.returncode, output)
