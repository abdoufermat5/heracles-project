"""Scale benchmark of the API v2: latency and LDAP round trips per scenario.

Runs the full application on a directory of ``--users`` accounts and ``users / 10`` groups
(the demo tree plus generated data, see ``benchdata.py``) and measures, per scenario, the
p50/p95 latency of a request and the LDAP work behind it:

* ``listing``: first page of users and groups (plain, sorted, deep page, one department);
* ``search``: free-text search;
* ``bulk``: one multiple edit of 100 users;
* ``acl``: the same reads and a bulk edit as a delegated administrator, a non-administrator
  whose roles are scoped to one department, so every entry goes through the ACL evaluation;
* ``login``: a user signs in (look-up by login, then a bind);
* ``api``: the endpoints behind the dashboard (types, tree, counters) and one object.

Backends: ``--backend memory`` (default, the in-memory demo directory) or ``--backend ldap``
against a server loaded by ``bench_ldap.py`` (needs python-ldap, ``--extra ldap``). The memory
directory answers in microseconds; the operation counts predict latency on a real server.

    uv run python bench/bench.py [--users 5000] [--repeat 20] [--json out.json]
        [--markdown out.md] [--profile PATH] [--no-check]
    uv run --extra ldap python bench/bench.py --backend ldap --ldap-uri ldap://127.0.0.1:1389 \
        --users 50000     # after `python bench/bench_ldap.py up --users 50000`

``ops`` is the number of directory operations of one request, ``trips`` the number of LDAP
requests on the wire (a paged search costs one per page of 500 entries), ``entries`` the
entries the searches returned. The script exits with status 1 when the p95 of an ``api``
endpoint exceeds its budget in ``P95_BUDGET_MS`` (measured at 5000 users on the memory
backend, about 2x headroom); budgets apply to the default ``--users`` only. Regressions
against a stored baseline are checked by ``bench_compare.py``.
"""

from __future__ import annotations

import argparse
import cProfile
import datetime
import json
import logging
import math
import os
import platform
import pstats
import statistics
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import benchdata
import httpx
import structlog
from fastapi.testclient import TestClient

import heracles
from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.ldap.client import DirectoryClient, Entry
from heracles.ldap.config import DirectoryConfig
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app

FORMAT = 1
#: p95 budget in milliseconds per endpoint at ``DEFAULT_USERS`` users (memory backend).
P95_BUDGET_MS: dict[str, float] = {
    "types": 100,
    "tree": 600,
    "dashboard": 1000,
    "users page (sub)": 1000,
    "users page (one)": 1100,
    "users search": 430,
    "users page 40": 210,
    "groups page": 140,
    "user detail": 155,
}
DEFAULT_USERS = 5000
BULK_SIZE = 100
PAGE_SIZE = 500
_COUNTED = frozenset(
    {"search", "search_primary", "get", "get_primary", "add", "modify", "delete", "rename"}
    | {"check_password"}
)


def p95(timings: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    ordered = sorted(timings)
    return ordered[max(0, -(-len(ordered) * 95 // 100) - 1)]


class CountingDirectory:
    """Wraps a directory client and counts what the application asks of it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.ops = 0
        self.trips = 0
        self.entries = 0

    def reset(self) -> None:
        self.ops = self.trips = self.entries = 0

    @property
    def base_dn(self) -> str:
        return self._inner.base_dn

    def _counted_search(self, name: str, *args: Any, **kwargs: Any) -> Iterator[Entry]:
        self.ops += 1
        found = list(getattr(self._inner, name)(*args, **kwargs))
        self.entries += len(found)
        page = kwargs.get("page_size", PAGE_SIZE)
        self.trips += max(1, math.ceil(len(found) / page))
        return iter(found)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in _COUNTED:
            return attr
        if name in ("search", "search_primary"):
            return lambda *a, **k: self._counted_search(name, *a, **k)

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.ops += 1
            self.trips += 1
            return attr(*args, **kwargs)

        return counted


# ---------------------------------------------------------------------------- scenarios


@dataclass
class Scenario:
    name: str
    group: str
    #: Called before each run, untimed; returns the request to time.
    prepare: Callable[[int], Callable[[], httpx.Response]]
    #: Raises when the response is not what the scenario is meant to produce.
    check: Callable[[httpx.Response], None] | None = None
    #: Writes many entries: a warm-up run would double a long scenario (``--warmup light``).
    heavy: bool = False


def _expect_ok(name: str) -> Callable[[httpx.Response], None]:
    def check(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise SystemExit(f"{name}: HTTP {response.status_code} {response.text[:300]}")

    return check


def _bulk_check(name: str) -> Callable[[httpx.Response], None]:
    def check(response: httpx.Response) -> None:
        _expect_ok(name)(response)
        failed = [r for r in response.json()["results"] if not r["ok"]]
        if failed:
            raise SystemExit(f"{name}: {len(failed)} of {BULK_SIZE} edits failed: {failed[0]}")

    return check


def login_client(app: Any, username: str, password: str) -> TestClient:
    client = TestClient(app, base_url="http://testserver")
    token = client.get("/api/v2/auth/csrf").json()["token"]
    response = client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": username, "password": password},
        headers={"X-CSRF-Token": token},
    )
    response.raise_for_status()
    return client


def build_scenarios(app: Any, users: int) -> list[Scenario]:
    admin = login_client(app, "admin", demo.DEMO_PASSWORD)
    manager = login_client(app, benchdata.MANAGER_UID, demo.DEMO_PASSWORD)
    api = "/api/v2"
    paris = quote(f"ou=paris,{demo.BASE}")
    lyon_base = quote(f"ou=lyon,{demo.BASE}")
    probe = min(users - 1, 42)
    one_user = quote(benchdata.user_dn(probe), safe="")
    exact = benchdata.uid(probe)
    scenarios: list[Scenario] = []

    def get(
        name: str, group: str, client: TestClient, path: str
    ) -> None:  # one GET, checked for success
        scenarios.append(
            Scenario(name, group, lambda _n: lambda: client.get(path), _expect_ok(name))
        )

    get("types", "api", admin, f"{api}/types")
    get("tree", "api", admin, f"{api}/tree")
    get("dashboard", "api", admin, f"{api}/dashboard")
    get("user detail", "api", admin, f"{api}/objects/user/{one_user}")

    get("users page (sub)", "listing", admin, f"{api}/objects/user?scope=sub&limit=50")
    get(
        "users sorted",
        "listing",
        admin,
        f"{api}/objects/user?scope=sub&limit=50&sort=sn&order=desc",
    )
    get(
        "users page 40",
        "listing",
        admin,
        f"{api}/objects/user?scope=sub&limit=50&offset={min(2000, users // 2)}",
    )
    get("users page (one)", "listing", admin, f"{api}/objects/user?base={paris}&limit=50")
    get("groups page", "listing", admin, f"{api}/objects/group?scope=sub&limit=50")
    get(
        "groups sorted",
        "listing",
        admin,
        f"{api}/objects/group?scope=sub&limit=50&sort=cn&order=desc",
    )

    get("users search", "search", admin, f"{api}/objects/user?scope=sub&q=number0004&limit=50")
    get("users search (exact)", "search", admin, f"{api}/objects/user?scope=sub&q={exact}&limit=50")
    get("groups search", "search", admin, f"{api}/objects/group?scope=sub&q=team0004&limit=50")

    def bulk(client: TestClient, numbers: list[int], name: str) -> Scenario:
        dns = [benchdata.user_dn(i) for i in numbers]
        token = client.get(f"{api}/auth/csrf").json()["token"]
        found = client.post(
            f"{api}/objects/user/_bulk/attributes",
            json={"dns": dns},
            headers={"X-CSRF-Token": token},
        )
        found.raise_for_status()
        tab = next(
            (t for t, names in found.json()["attributes"].items() if "description" in names), None
        )
        if tab is None:
            raise SystemExit(f"{name}: no tab of the user type allows editing the description")

        def prepare(n: int) -> Callable[[], httpx.Response]:
            changes = {tab: {"description": {"op": "set", "value": f"bench run {n}"}}}
            body = {"dns": dns, "changes": changes}
            return lambda: client.patch(
                f"{api}/objects/user/_bulk", json=body, headers={"X-CSRF-Token": token}
            )

        return Scenario(
            name,
            "bulk" if client is admin else "acl",
            prepare,
            _bulk_check(name),
            heavy=True,
        )

    # bulk edit: 100 users of the generated range, spread over both departments
    admin_numbers = list(
        range(min(1000, users - BULK_SIZE), min(1000, users - BULK_SIZE) + BULK_SIZE)
    )
    scenarios.append(bulk(admin, admin_numbers, "bulk edit 100"))

    get("acl users page", "acl", manager, f"{api}/objects/user?scope=sub&limit=50")
    get(
        "acl users sorted",
        "acl",
        manager,
        f"{api}/objects/user?scope=sub&limit=50&sort=sn&order=desc",
    )
    # a search needs read access to the searched attributes at its base: the delegated
    # administrator searches the department he manages (from the root it finds nothing)
    get(
        "acl users search",
        "acl",
        manager,
        f"{api}/objects/user?base={lyon_base}&scope=sub&q=number001&limit=50",
    )
    get(
        "acl user detail",
        "acl",
        manager,
        f"{api}/objects/user/{quote(benchdata.user_dn(0), safe='')}",
    )
    get("acl groups page", "acl", manager, f"{api}/objects/group?scope=sub&limit=50")
    lyon = [i for i in range(users) if benchdata.department(i) == "lyon"][-BULK_SIZE:]
    scenarios.append(bulk(manager, lyon, "acl bulk edit 100"))

    def login(n: int) -> Callable[[], httpx.Response]:
        client = TestClient(app, base_url="http://testserver")
        token = client.get(f"{api}/auth/csrf").json()["token"]
        body = {
            "directory": "main",
            "username": benchdata.uid(n % min(users, benchdata.LOGIN_USERS)),
            "password": benchdata.PASSWORD,
        }
        return lambda: client.post(f"{api}/auth/login", json=body, headers={"X-CSRF-Token": token})

    scenarios.append(Scenario("login", "login", login, _expect_ok("login")))
    return scenarios


# ------------------------------------------------------------------------------ running


def measure(
    scenario: Scenario,
    directory: CountingDirectory,
    args: argparse.Namespace,
    profiler: cProfile.Profile | None,
) -> dict[str, Any]:
    """Warm up once, then run ``--repeat`` times (``--max-seconds`` may stop earlier)."""
    if args.warmup == "all" or (args.warmup == "light" and not scenario.heavy):
        # caches, connections; also fails early
        response = scenario.prepare(0)()
        if scenario.check:
            scenario.check(response)
    timings: list[float] = []
    #: LDAP work and body size of each run: caches (ACL, configuration) that expire between
    #: runs make single runs differ, the median is the steady state
    work: dict[str, list[int]] = {"ops": [], "trips": [], "entries": [], "bytes": []}
    started = time.monotonic()
    for n in range(1, args.repeat + 1):
        run = scenario.prepare(n)
        directory.reset()
        if profiler:
            profiler.enable()
        t0 = time.perf_counter()
        response = run()
        timings.append((time.perf_counter() - t0) * 1000)
        if profiler:
            profiler.disable()
        if scenario.check:
            scenario.check(response)
        work["ops"].append(directory.ops)
        work["trips"].append(directory.trips)
        work["entries"].append(directory.entries)
        work["bytes"].append(len(response.content))
        if len(timings) >= args.min_runs and time.monotonic() - started > args.max_seconds:
            break
    return {
        "group": scenario.group,
        "p50_ms": round(statistics.median(timings), 2),
        "p95_ms": round(p95(timings), 2),
        "max_ms": round(max(timings), 2),
        **{name: round(statistics.median(values)) for name, values in work.items()},
        "runs": len(timings),
    }


def calibrate() -> float:
    """Milliseconds a fixed pure-Python workload takes here (to compare machines)."""
    best = float("inf")
    for _ in range(5):
        t0 = time.perf_counter()
        table = {str(i): i * i for i in range(200_000)}
        sum(sorted(table.values(), reverse=True)[:1000])
        best = min(best, time.perf_counter() - t0)
    return round(best * 1000, 1)


def _first_line(path: str, key: str) -> str:
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith(key):
                return line.split(":", 1)[-1].split("=", 1)[-1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def machine() -> dict[str, Any]:
    mem_kib = (
        int(_first_line("/proc/meminfo", "MemTotal").split()[0])
        if os.path.exists("/proc/meminfo")
        else 0
    )
    return {
        "cpu": _first_line("/proc/cpuinfo", "model name"),
        "cores": os.cpu_count(),
        "ram_gb": round(mem_kib / 1024 / 1024, 1),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }


def make_directory(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    """The directory client of the chosen backend and a description of it."""
    if args.backend == "memory":
        directory = MemoryDirectory(demo.BASE)
        t0 = time.perf_counter()
        benchdata.load_memory(directory, args.users)
        return directory, {"backend": "memory", "load_seconds": round(time.perf_counter() - t0, 1)}
    from heracles.ldap.pyldap import PyLdapDirectory  # needs python-ldap

    config = DirectoryConfig(
        id="main",
        uri=args.ldap_uri,
        bind_dn=args.bind_dn,
        bind_password=args.bind_password,  # type: ignore[arg-type]
        base_dn=demo.BASE,
        pool_size=8,
        timeout=120,
    )
    client = PyLdapDirectory(config)
    last = client.get(benchdata.user_dn(args.users - 1))
    beyond = client.get(benchdata.user_dn(args.users))
    if last is None or beyond is not None:
        raise SystemExit(
            f"the directory at {args.ldap_uri} does not hold {args.users} generated users "
            "(load it with: python bench/bench_ldap.py up --users N)"
        )
    info = {"backend": "ldap", "server": args.server, "indexes": args.indexes}
    import ldap  # type: ignore[import-not-found]

    info["python_ldap"] = ldap.__version__
    return client, info


def markdown_table(result: dict[str, Any]) -> str:
    meta = result["meta"]
    lines = [
        f"{meta['users']} users, {meta['groups']} groups, backend `{meta['directory']['backend']}`"
        + (
            f" ({meta['directory'].get('indexes', '')} indexes)"
            if meta["directory"].get("indexes")
            else ""
        )
        + f", {meta['date']}",
        "",
        "| group | scenario | p50 ms | p95 ms | ops | trips | entries | KiB | runs |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in result["scenarios"].items():
        lines.append(
            f"| {row['group']} | {name} | {row['p50_ms']:g} | {row['p95_ms']:g} | {row['ops']} "
            f"| {row['trips']} | {row['entries']} | {row['bytes'] / 1024:.1f} | {row['runs']} |"
        )
    return "\n".join(lines) + "\n"


def print_table(result: dict[str, Any]) -> None:
    print(
        f"{'scenario':<22}{'group':<9}{'p50 ms':>10}{'p95 ms':>10}"
        f"{'ops':>6}{'trips':>7}{'entries':>9}{'KiB':>8}"
    )
    for name, row in result["scenarios"].items():
        print(
            f"{name:<22}{row['group']:<9}{row['p50_ms']:>10.1f}{row['p95_ms']:>10.1f}"
            f"{row['ops']:>6}{row['trips']:>7}{row['entries']:>9}{row['bytes'] / 1024:>8.1f}",
            flush=True,
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--repeat", type=int, default=20, help="runs per scenario (at most)")
    parser.add_argument(
        "--max-seconds", type=float, default=60, help="stop repeating a scenario after this long"
    )
    parser.add_argument("--min-runs", type=int, default=3, help="runs even past --max-seconds")
    parser.add_argument(
        "--warmup",
        choices=("all", "light", "none"),
        default="all",
        help="one unmeasured run first: of every scenario, all but the bulk edits (which can "
        "take minutes on a huge in-memory directory), or none",
    )
    parser.add_argument("--backend", choices=("memory", "ldap"), default="memory")
    parser.add_argument("--ldap-uri", default="ldap://127.0.0.1:1389")
    parser.add_argument("--bind-dn", default=f"cn=admin,{demo.BASE}")
    parser.add_argument("--bind-password", default="admin")
    parser.add_argument("--server", default="", help="description of the server (for the report)")
    parser.add_argument("--indexes", default="", help="index set of the server (for the report)")
    parser.add_argument("--json", help="write the results here")
    parser.add_argument("--markdown", help="write the results as a Markdown table here")
    parser.add_argument("--no-check", action="store_true", help="do not enforce the p95 budgets")
    parser.add_argument("--profile", help="write cProfile stats of the measured requests here")
    args = parser.parse_args(argv)

    # request logs would drown the table (and their cost is not what is measured)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    raw, directory_info = make_directory(args)
    directory = CountingDirectory(raw)
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Bench"})
    settings.session.cookie_secure = False
    clients: dict[str, DirectoryClient] = {"main": directory}  # type: ignore[dict-item]
    app = create_full_app(settings, clients)
    scenarios = build_scenarios(app, args.users)

    profiler = cProfile.Profile() if args.profile else None
    result: dict[str, Any] = {
        "format": FORMAT,
        "meta": {
            "date": datetime.date.today().isoformat(),
            "users": args.users,
            "groups": benchdata.group_count(args.users),
            "repeat": args.repeat,
            "heracles": heracles.__version__,
            "machine": machine(),
            "calibration_ms": calibrate(),
            "directory": directory_info,
        },
        "scenarios": {},
    }
    print(f"{args.users} users, {args.repeat} runs at most per scenario", flush=True)
    over: list[str] = []
    for scenario in scenarios:
        row = measure(scenario, directory, args, profiler)
        result["scenarios"][scenario.name] = row
        print(f"  done {scenario.name}: p50 {row['p50_ms']:.1f} ms", file=sys.stderr, flush=True)
        budget = P95_BUDGET_MS.get(scenario.name)
        if budget is not None and row["p95_ms"] > budget:
            over.append(f"{scenario.name}: p95 {row['p95_ms']:.1f} ms > budget {budget:.0f} ms")
    print_table(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n")
    if args.markdown:
        Path(args.markdown).write_text(markdown_table(result))
    if profiler and args.profile:
        profiler.dump_stats(args.profile)
        pstats.Stats(args.profile).sort_stats("cumulative").print_stats(35)
    close = getattr(raw, "close", None)
    if args.backend == "ldap" and close is not None:
        close()
    budgets_apply = args.backend == "memory" and args.users == DEFAULT_USERS
    if over and not args.no_check and budgets_apply:
        print("\nbudget exceeded:\n  " + "\n  ".join(over))
        raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
