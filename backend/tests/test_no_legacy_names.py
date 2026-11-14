"""No legacy identifier or third-party product name outside the migration table.

Legacy LDAP names may appear only in ``heracles/migrate/legacy_map.py`` and the
migration tests; everywhere else Heracles uses its own ``hrc*`` schema.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = (
    "backend/src/heracles/migrate/legacy_map.py",
    "backend/tests/migrate/",
    "backend/tests/test_no_legacy_names.py",
)
SKIPPED_SUFFIXES = (".png", ".jpg", ".ico", ".woff", ".woff2", ".svg", ".lock")
SKIPPED_NAMES = ("pnpm-lock.yaml", "uv.lock")
LEGACY = re.compile(
    r"\b(?:fd|gosa|goto)[A-Z_]"  # legacy LDAP prefixes
    r"|\bgo[A-Z][a-z]+[A-Z]"  # goXxxYyy legacy classes
    r"|\b[Ff]usion(?!n)|FUSION"  # product name (not the French "fusionner")
    r"|\bFD\b"
)
PRODUCTS = re.compile(
    r"\b(?:"
    r"cyrus|dovecot|ejbca|freeradius|nextcloud|postfix|pure-?ftpd|samba|sogo"
    r"|spamassassin|zimbra|mailinblack|gpg|gnupg"
    r")\b",
    re.IGNORECASE,
)
"""Third-party product names of the plugins, replaced by generic ids and labels."""


def _tracked_files() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [p for p in out.splitlines() if p]


def test_no_legacy_names_outside_the_migration_table() -> None:
    hits: list[str] = []
    for rel in _tracked_files():
        if rel.startswith(ALLOWED) or rel.endswith(SKIPPED_SUFFIXES):
            continue
        if rel.rsplit("/", 1)[-1] in SKIPPED_NAMES:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if LEGACY.search(line) or PRODUCTS.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    assert hits == [], "legacy names found:\n" + "\n".join(hits)
