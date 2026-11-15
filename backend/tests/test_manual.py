"""The generated manual pages match the code (run ``scripts/gen_manual.py`` after a change)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_manual.py"


def test_generated_pages_are_up_to_date() -> None:
    # a fresh interpreter: the test suite patches the core plugin profile
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
