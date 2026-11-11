"""Latency and directory round-trip benchmark of the hot API v2 endpoints.

Runs the full application on the in-memory demo directory grown to ``--users``
accounts, as a delegated (non-bootstrap) administrator so ACLs are evaluated.
The in-memory directory answers in microseconds, so the ``calls`` column (LDAP
operations per request) is what predicts latency against a real server.

    uv run python scripts/bench.py [--users 5000] [--repeat 5] [--profile PATH]
"""

from __future__ import annotations

import argparse
import cProfile
import logging
import pstats
import statistics
import time
from collections.abc import Iterator, Sequence
from urllib.parse import quote

import structlog
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings
from heracles.ldap.client import Entry, Scope
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app


class CountingDirectory(MemoryDirectory):
    """Counts read operations."""

    calls = 0

    def search(
        self,
        base: str,
        filterstr: str = "(objectClass=*)",
        scope: Scope = Scope.SUBTREE,
        attrs: Sequence[str] | None = None,
        *,
        size_limit: int = 0,
        page_size: int = 500,
    ) -> Iterator[Entry]:
        self.calls += 1
        return super().search(
            base, filterstr, scope, attrs, size_limit=size_limit, page_size=page_size
        )

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        self.calls += 1
        return super().get(dn, attrs)


def build_directory(users: int) -> CountingDirectory:
    source = demo.build_demo_directory()
    directory = CountingDirectory(demo.BASE)
    directory.set_schema_object_classes(source.schema_object_classes())
    for dn in source.dns():
        entry = source.get(dn)
        assert entry is not None
        directory.add(dn, entry.attrs)
    directory.set_password(demo.ADMIN_DN, demo.DEMO_PASSWORD)
    people = f"ou=people,ou=paris,{demo.BASE}"
    members: list[bytes] = []
    for i in range(users):
        uid = f"user{i:05d}"
        dn = f"uid={uid},{people}"
        directory.add(
            dn,
            {
                "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
                "uid": [uid.encode()],
                "givenName": [b"User"],
                "sn": [f"Number{i:05d}".encode()],
                "cn": [f"User Number{i:05d}".encode()],
                "mail": [f"{uid}@heracles.test".encode()],
                "userPassword": [b"{SSHA}c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0"],
            },
        )
        if i % 10 == 0:
            members.append(dn.encode())
    for g in range(50):
        directory.add(
            f"cn=team{g:02d},ou=groups,ou=paris,{demo.BASE}",
            {
                "objectClass": [b"groupOfNames"],
                "cn": [f"team{g:02d}".encode()],
                "member": members[g::50] or [demo.ADMIN_DN.encode()],
            },
        )
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=5000)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--profile", help="write cProfile stats of the measured requests here")
    args = parser.parse_args()

    # request logs would drown the table (and their cost is not what is measured)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    directory = build_directory(args.users)
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Bench"})
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": directory})
    client = TestClient(app, base_url="http://testserver")
    token = client.get("/api/v2/auth/csrf").json()["token"]
    login = client.post(
        "/api/v2/auth/login",
        json={"directory": "main", "username": "admin", "password": demo.DEMO_PASSWORD},
        headers={"X-CSRF-Token": token},
    )
    login.raise_for_status()

    paris = quote(f"ou=paris,{demo.BASE}")
    one_user = quote(f"uid=user00042,ou=people,ou=paris,{demo.BASE}", safe="")
    endpoints = {
        "types": "/api/v2/types",
        "tree": "/api/v2/tree",
        "dashboard": "/api/v2/dashboard",
        "users page (sub)": "/api/v2/objects/user?scope=sub&limit=50",
        "users page (one)": f"/api/v2/objects/user?base={paris}&limit=50",
        "users search": "/api/v2/objects/user?scope=sub&q=number0004&limit=50",
        "users page 40": "/api/v2/objects/user?scope=sub&limit=50&offset=2000",
        "groups page": "/api/v2/objects/group?scope=sub&limit=50",
        "user detail": f"/api/v2/objects/user/{one_user}",
    }
    for path in endpoints.values():  # warm-up, fail early
        client.get(path).raise_for_status()

    profiler = cProfile.Profile() if args.profile else None
    print(f"{args.users} users, {args.repeat} runs each")
    print(f"{'endpoint':<20}{'p50 ms':>10}{'max ms':>10}{'calls':>8}{'bytes':>9}")
    for name, path in endpoints.items():
        timings: list[float] = []
        calls = size = 0
        for _ in range(args.repeat):
            directory.calls = 0
            if profiler:
                profiler.enable()
            started = time.perf_counter()
            response = client.get(path)
            timings.append((time.perf_counter() - started) * 1000)
            if profiler:
                profiler.disable()
            calls, size = directory.calls, len(response.content)
        print(
            f"{name:<20}{statistics.median(timings):>10.1f}{max(timings):>10.1f}{calls:>8}{size:>9}"
        )
    if profiler and args.profile:
        profiler.dump_stats(args.profile)
        pstats.Stats(args.profile).sort_stats("cumulative").print_stats(35)


if __name__ == "__main__":
    main()
