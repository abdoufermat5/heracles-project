#!/usr/bin/env python3
"""Fail when the release tag and the package versions disagree.

Compares the git tag (``v1.2.3`` or ``1.2.3``; optional first argument, no tag check when
omitted), the backend (``backend/pyproject.toml``), the frontend (``frontend/package.json``)
and the Helm chart (``deploy/helm/heracles/Chart.yaml``: ``version`` and ``appVersion``).
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def chart_field(text: str, key: str) -> str:
    match = re.search(rf"^{key}:\s*[\"']?([^\"'\s#]+)[\"']?\s*(?:#.*)?$", text, re.M)
    if not match:
        raise SystemExit(f"Chart.yaml has no {key}")
    return match.group(1)


def collect(root: Path = ROOT) -> dict[str, str]:
    chart = (root / "deploy/helm/heracles/Chart.yaml").read_text()
    pyproject = tomllib.loads((root / "backend/pyproject.toml").read_text())
    return {
        "backend": pyproject["project"]["version"],
        "frontend": json.loads((root / "frontend/package.json").read_text())["version"],
        "chart version": chart_field(chart, "version"),
        "chart appVersion": chart_field(chart, "appVersion"),
    }


def main(argv: list[str]) -> int:
    versions = collect()
    if len(argv) > 1:
        versions = {"tag": argv[1].removeprefix("v"), **versions}
    for name, value in versions.items():
        print(f"{name:18} {value}")
    if len(set(versions.values())) != 1:
        print("error: versions disagree", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
