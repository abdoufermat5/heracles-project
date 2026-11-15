"""Compare a benchmark run with a committed baseline; exit 1 on a regression.

    python scripts/bench_compare.py scripts/bench-baseline.json current.json [--factor 2]

A scenario regresses when, against the baseline, its median latency or one of its LDAP counters
(operations, round trips, entries) grew by more than ``--factor``. Small baselines get a floor
(``--floor-ms``, and one per counter) so that a 0.4 ms request taking 1.1 ms is not a failure.
The latency limit is scaled by how much slower the current machine is than the one that made
the baseline (the ``calibration_ms`` of both files; a faster machine does not tighten it).
A scenario missing from the current run fails too: change the baseline on purpose
(``make bench-baseline``) when scenarios are renamed or removed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Counters compared besides the latency, with their floors.
COUNTERS = {"ops": 4, "trips": 4, "entries": 100}


def speed_factor(baseline: dict[str, Any], current: dict[str, Any]) -> float:
    """How many times slower the current machine runs the calibration (never below 1)."""
    base = float(baseline["meta"].get("calibration_ms") or 0)
    now = float(current["meta"].get("calibration_ms") or 0)
    if base <= 0 or now <= 0:
        return 1.0
    return max(1.0, now / base)


def compare(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    factor: float = 2.0,
    floor_ms: float = 5.0,
) -> list[str]:
    """Failures, one line each (empty when the current run is within the limits)."""
    speed = speed_factor(baseline, current)
    failures: list[str] = []
    now_rows: dict[str, Any] = current["scenarios"]
    for name, base in baseline["scenarios"].items():
        row = now_rows.get(name)
        if row is None:
            failures.append(f"{name}: missing from the current run")
            continue
        limit = factor * max(float(base["p50_ms"]), floor_ms) * speed
        if float(row["p50_ms"]) > limit:
            failures.append(
                f"{name}: p50 {row['p50_ms']:g} ms > {limit:.1f} ms "
                f"({factor:g}x baseline {base['p50_ms']:g} ms, machine factor {speed:.2f})"
            )
        for counter, floor in COUNTERS.items():
            allowed = factor * max(float(base[counter]), floor)
            if float(row[counter]) > allowed:
                failures.append(
                    f"{name}: {counter} {row[counter]} > {allowed:g} "
                    f"({factor:g}x baseline {base[counter]})"
                )
    return failures


def report(baseline: dict[str, Any], current: dict[str, Any]) -> str:
    """A table of the p50 and operation ratios, current over baseline."""
    lines = [
        f"{'scenario':<24}{'p50 base':>10}{'p50 now':>10}{'ratio':>8}{'ops base':>10}{'ops now':>9}"
    ]
    for name, base in baseline["scenarios"].items():
        row = current["scenarios"].get(name)
        if row is None:
            lines.append(f"{name:<24}{'-':>10}{'missing':>10}")
            continue
        ratio = float(row["p50_ms"]) / max(float(base["p50_ms"]), 0.01)
        lines.append(
            f"{name:<24}{base['p50_ms']:>10g}{row['p50_ms']:>10g}{ratio:>8.2f}"
            f"{base['ops']:>10}{row['ops']:>9}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--factor", type=float, default=2.0, help="allowed growth (default 2)")
    parser.add_argument("--floor-ms", type=float, default=5.0, help="latency floor of the baseline")
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text())
    current = json.loads(args.current.read_text())
    for label, data in (("baseline", baseline), ("current", current)):
        if data.get("format") != 1:
            print(f"{label}: unsupported benchmark file format {data.get('format')!r}")
            return 2
    if baseline["meta"]["users"] != current["meta"]["users"]:
        print(
            f"the runs are not comparable: {baseline['meta']['users']} users in the baseline, "
            f"{current['meta']['users']} in the current run"
        )
        return 2
    print(report(baseline, current))
    failures = compare(baseline, current, factor=args.factor, floor_ms=args.floor_ms)
    if failures:
        print(f"\n{len(failures)} regression(s) beyond {args.factor:g}x:")
        print("\n".join(f"  {f}" for f in failures))
        return 1
    print(f"\nno scenario regressed beyond {args.factor:g}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
