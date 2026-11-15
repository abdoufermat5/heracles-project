"""``scripts/changelog.py``: conventional commits grouped per version."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "changelog.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("changelog", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["changelog"] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


def test_parse_types_scopes_and_breaking_changes() -> None:
    cl = load()
    assert cl.parse("a" * 40, "feat(acl): add roles").scope == "acl"
    assert cl.parse("a" * 40, "merge(scim): stream") is None
    assert cl.parse("a" * 40, "Update readme") is None
    bang = cl.parse("b" * 40, "feat(api)!: drop v1")
    assert bang.breaking == "drop v1"
    message = "fix(config): rename key\n\nBREAKING CHANGE: `a.b` is now\n`a.c`.\n"
    footer = cl.parse("c" * 40, message)
    assert footer.breaking == "`a.b` is now `a.c`."


def test_render_puts_breaking_changes_first() -> None:
    cl = load()
    release = cl.Release(
        "v1.0.0",
        "2030-01-01",
        [
            cl.parse("1" * 40, "fix(api): typo"),
            cl.parse("2" * 40, "feat(acl)!: new rights format"),
            cl.parse("3" * 40, "docs: guide"),
        ],
    )
    text = cl.render(release)
    assert text.startswith("## v1.0.0 — 2030-01-01")
    assert text.index("### Breaking changes") < text.index("### Features") < text.index("### Fixes")
    assert "- **acl:** new rights format (22222222)" in text
