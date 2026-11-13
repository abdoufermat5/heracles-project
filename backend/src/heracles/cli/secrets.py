"""Secrets for the command line: read from a file, or from standard input (``-``).

A secret typed as an option value stays in the process list and the shell history; the
commands accept ``--password-file`` / ``--to-file`` (and an environment variable) so that
it does not have to be passed on the command line.
"""

from __future__ import annotations

import sys
from pathlib import Path


class SecretError(Exception):
    """The secret cannot be read; the message is shown to the operator."""


def read_secret_file(path: str, what: str) -> str:
    """The content of ``path`` without its trailing newline; ``-`` reads standard input."""
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SecretError(f"cannot read {what} file {path}: {exc.strerror or exc}") from exc
    return text.rstrip("\r\n")
