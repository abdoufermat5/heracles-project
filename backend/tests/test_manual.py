"""The generated manual pages match the code (run ``scripts/gen_manual.py`` after a change)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_manual.py"


def test_generated_pages_are_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location("gen_manual", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_manual"] = module
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0, (
        "run: uv --directory backend run python ../scripts/gen_manual.py"
    )
