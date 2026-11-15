"""The benchmark scripts (backend/scripts): dataset, regression check, a tiny end-to-end run."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog

from heracles.ldap.ldif import parse_ldif

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str) -> Any:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def _keep_logging_config() -> Iterator[None]:
    """``bench.main`` filters the log level process-wide, as the command line tool should."""
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


@pytest.fixture(scope="module")
def data() -> Any:
    return _load("benchdata")


@pytest.fixture(scope="module")
def compare() -> Any:
    return _load("bench_compare")


# ------------------------------------------------------------------------------- dataset


def test_groups_hold_about_twenty_users_and_cover_everyone(data: Any) -> None:
    users, groups = 1000, data.group_count(1000)
    assert groups == 100
    seen: set[int] = set()
    for k in range(groups):
        members = data.group_members(k, users, groups)
        assert 15 <= len(members) <= 25
        seen.update(members)
    assert seen == set(range(users))


def test_departments_split_users_forty_sixty(data: Any) -> None:
    lyon = sum(data.department(i) == "lyon" for i in range(1000))
    assert lyon == 400
    assert data.department(0) == "lyon"
    assert data.MANAGER_DN.endswith("ou=people,ou=lyon,dc=heracles,dc=test")


def test_ldif_holds_the_demo_tree_then_the_generated_entries(data: Any, tmp_path: Path) -> None:
    out = tmp_path / "bench.ldif"
    count = data.write_ldif(out, 50)
    entries = parse_ldif(out.read_text(encoding="utf-8"))
    assert len(entries) == count
    dns = [e.dn.lower() for e in entries]
    assert len(set(dns)) == len(dns)
    # every parent precedes its children (a server refuses an orphan)
    base = "dc=heracles,dc=test"
    seen: set[str] = set()
    for dn in dns:
        if dn != base:
            assert dn.split(",", 1)[1] in seen, dn
        seen.add(dn)
    by_dn = {e.dn.lower(): e for e in entries}
    hashed = by_dn[data.user_dn(3).lower()].text("userPassword")
    assert hashed is not None
    assert hashed.startswith("{SSHA}")
    admin = by_dn["uid=admin,ou=people,dc=heracles,dc=test"]
    assert admin.text("userPassword") == "heracles"  # no {CLEARTEXT} for a real server


def test_memory_directory_knows_the_login_passwords(data: Any) -> None:
    from heracles import demo
    from heracles.ldap.memory import MemoryDirectory

    directory = MemoryDirectory(demo.BASE)
    data.load_memory(directory, 30)
    assert directory.check_password(data.user_dn(2), data.PASSWORD)
    assert not directory.check_password(data.user_dn(2), "wrong")
    assert directory.get(data.group_dn(0)) is not None
    assert directory.get(data.user_dn(29)) is not None
    assert directory.get(data.user_dn(30)) is None


# ---------------------------------------------------------------------- regression check


def _run(users: int = 2000, calibration: float = 100.0, **rows: dict[str, float]) -> dict[str, Any]:
    return {
        "format": 1,
        "meta": {"users": users, "calibration_ms": calibration},
        "scenarios": {
            name: {"p50_ms": 50.0, "ops": 10, "trips": 10, "entries": 500, **row}
            for name, row in rows.items()
        },
    }


def test_identical_runs_pass(compare: Any) -> None:
    baseline = _run(listing={}, search={"p50_ms": 20.0})
    assert compare.compare(baseline, copy.deepcopy(baseline)) == []


def test_growth_within_the_factor_passes(compare: Any) -> None:
    baseline = _run(listing={})
    current = _run(listing={"p50_ms": 99.0, "ops": 20, "trips": 20, "entries": 1000})
    assert compare.compare(baseline, current) == []


def test_slower_than_twice_the_baseline_fails(compare: Any) -> None:
    failures = compare.compare(_run(listing={}), _run(listing={"p50_ms": 101.0}))
    assert len(failures) == 1
    assert "listing: p50 101 ms > 100.0 ms" in failures[0]


@pytest.mark.parametrize("counter", ["ops", "trips", "entries"])
def test_more_than_twice_the_ldap_work_fails(compare: Any, counter: str) -> None:
    current = _run(listing={counter: {"ops": 21, "trips": 21, "entries": 1001}[counter]})
    failures = compare.compare(_run(listing={}), current)
    assert [f.split(":")[1].split()[0] for f in failures] == [counter]


def test_tiny_baselines_have_a_floor(compare: Any) -> None:
    baseline = _run(types={"p50_ms": 0.4, "ops": 0, "trips": 0, "entries": 0})
    # 6x the baseline but under 2x the floor: noise, not a regression
    ok = _run(types={"p50_ms": 2.4, "ops": 5, "trips": 5, "entries": 150})
    assert compare.compare(baseline, ok) == []
    bad = _run(types={"p50_ms": 12.0, "ops": 9, "trips": 9, "entries": 250})
    assert len(compare.compare(baseline, bad)) == 4


def test_a_slower_machine_gets_a_proportionally_higher_latency_limit(compare: Any) -> None:
    baseline = _run(calibration=100.0, listing={})
    slow = _run(calibration=300.0, listing={"p50_ms": 290.0})
    assert compare.compare(baseline, slow) == []
    assert compare.compare(baseline, _run(calibration=300.0, listing={"p50_ms": 301.0}))
    # a faster machine does not tighten the limit
    assert compare.compare(baseline, _run(calibration=50.0, listing={"p50_ms": 99.0})) == []


def test_a_missing_scenario_fails(compare: Any) -> None:
    failures = compare.compare(_run(listing={}, search={}), _run(listing={}))
    assert failures == ["search: missing from the current run"]


def test_cli_exit_codes(compare: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline, ok, bad, other = (tmp_path / n for n in ("base", "ok", "bad", "other"))
    baseline.write_text(json.dumps(_run(listing={})))
    ok.write_text(json.dumps(_run(listing={"p50_ms": 60.0})))
    bad.write_text(json.dumps(_run(listing={"p50_ms": 500.0})))
    other.write_text(json.dumps(_run(users=500, listing={})))
    assert compare.main([str(baseline), str(ok)]) == 0
    assert compare.main([str(baseline), str(bad)]) == 1
    assert "1 regression(s) beyond 2x" in capsys.readouterr().out
    assert compare.main([str(baseline), str(other)]) == 2


# --------------------------------------------------------------------------- end to end


def test_a_small_run_reports_every_scenario_and_matches_its_own_baseline(
    tmp_path: Path, compare: Any
) -> None:
    bench = _load("bench")
    out, table = tmp_path / "run.json", tmp_path / "run.md"
    bench.main(
        [
            "--users",
            "120",
            "--repeat",
            "1",
            "--min-runs",
            "1",
            "--warmup",
            "none",
            "--json",
            str(out),
            "--markdown",
            str(table),
        ]
    )
    result = json.loads(out.read_text())
    assert result["meta"]["users"] == 120
    assert result["meta"]["groups"] == 12
    assert result["meta"]["directory"]["backend"] == "memory"
    groups = {row["group"] for row in result["scenarios"].values()}
    assert groups == {"api", "listing", "search", "bulk", "acl", "login"}
    for name in ("bulk edit 100", "acl bulk edit 100", "login", "acl users page"):
        assert result["scenarios"][name]["ops"] > 0
    assert result["scenarios"]["bulk edit 100"]["runs"] == 1
    assert "| listing | users page (sub) |" in table.read_text()
    assert compare.compare(result, result) == []
