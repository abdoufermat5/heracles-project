"""Throwaway OpenLDAP server loaded with the benchmark dataset (needs Docker).

    python bench/bench_ldap.py up --users 50000 [--indexes tuned] [--port 0]   # prints JSON
    python bench/bench_ldap.py down NAME
    python bench/bench_ldap.py run --users 50000 [--indexes tuned] [-- <bench.py options>]

``up`` generates the LDIF of ``benchdata`` (demo tree + users + groups), starts an OpenLDAP 2.6
container with the Heracles schema on a free loopback port (unique name ``hrc-bench-ldap-*``),
loads the data offline with ``slapadd -q`` (``--load ldapadd`` goes through the protocol
instead, much slower) and prints ``{"name", "uri", "bind_dn", "bind_password", "base_dn",
"server", "indexes", "entries", "load_seconds"}``. ``down`` removes the container and its
data volume.
The directory is reachable at ``uri`` with the bind DN of the printed JSON; the application
connects as that administrator and logs users in by binding.

``--indexes default`` keeps the image's indexes (objectClass, ou, cn, mail, sn, givenName);
``tuned`` adds equality indexes on ``uid``, ``member``, ``memberUid``, ``roleOccupant`` and
``hrcObjectDn`` (the attributes the console filters on), what a production directory has.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import benchdata

from heracles import demo

IMAGE = "bitnamilegacy/openldap:2.6"
ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "deploy" / "ldap" / "schema"
ADMIN_DN = f"cn=admin,{demo.BASE}"
ADMIN_PASSWORD = "admin"  # noqa: S105 - throwaway container bound to loopback
CONFIG_DN = "cn=admin,cn=config"
CONFIG_PASSWORD = "configpass"  # noqa: S105 - same
DATABASE_DN = "olcDatabase={2}mdb,cn=config"
BIN = "/opt/bitnami/openldap"
TUNED_INDEXES = ("uid,memberUid,member,roleOccupant,hrcObjectDn eq",)
MAP_SIZE = 8 * 1024**3


def docker(*args: str, check: bool = True, **kwargs: object) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(  # noqa: S603 - fixed argument vector
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        **kwargs,  # type: ignore[arg-type]
    )
    if check and done.returncode:
        raise SystemExit(f"docker {' '.join(args[:2])} failed:\n{done.stdout}{done.stderr}")
    return done


def remove(name: str) -> None:
    """Remove the container and its data volume (named like the container)."""
    docker("rm", "-f", name, check=False)
    docker("volume", "rm", "-f", name, check=False)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(name: str, *, loaded: bool, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout

    def log() -> str:
        done = docker("logs", name, check=False)
        return done.stdout + done.stderr

    # the image first runs a temporary slapd to configure itself: wait for the real one
    while "** Starting slapd **" not in log():
        if time.monotonic() > deadline:
            raise SystemExit(f"{name} did not start:\n{log()}")
        time.sleep(1)
    while time.monotonic() < deadline:
        probe = docker(
            "exec",
            name,
            "ldapsearch",
            "-x",
            "-H",
            "ldap://localhost:1389",
            "-b",
            demo.BASE,
            "-D",
            ADMIN_DN,
            "-w",
            ADMIN_PASSWORD,
            "-s",
            "base",
            "dn",
            check=False,
        )
        # 32: the suffix exists but not its entry yet (before the load)
        if probe.returncode == 0 or (probe.returncode == 32 and not loaded):
            return
        time.sleep(1)
    raise SystemExit(f"{name} did not become ready:\n{log()}")


def config_modify(name: str, ldif: str) -> None:
    docker(
        "exec",
        "-i",
        name,
        "ldapmodify",
        "-x",
        "-H",
        "ldap://localhost:1389",
        "-D",
        CONFIG_DN,
        "-w",
        CONFIG_PASSWORD,
        input=ldif,
    )


def tune(name: str, indexes: str) -> None:
    """Grow the database map (100k entries do not fit the image's 1 GiB) and add indexes."""
    lines = [
        f"dn: {DATABASE_DN}",
        "changetype: modify",
        "replace: olcDbMaxSize",
        f"olcDbMaxSize: {MAP_SIZE}",
    ]
    if indexes == "tuned":
        lines += ["-", "add: olcDbIndex", *(f"olcDbIndex: {i}" for i in TUNED_INDEXES)]
    config_modify(name, "\n".join(lines) + "\n")


def up(args: argparse.Namespace) -> dict[str, object]:
    name = f"hrc-bench-ldap-{secrets.token_hex(3)}"
    port = args.port or free_port()
    workdir = Path(tempfile.mkdtemp(prefix="hrc-bench-"))
    try:
        ldif = workdir / "bench.ldif"
        entries = benchdata.write_ldif(ldif, args.users)
        docker(
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:1389",
            "-e",
            f"LDAP_ROOT={demo.BASE}",
            "-e",
            "LDAP_ADMIN_USERNAME=admin",
            "-e",
            f"LDAP_ADMIN_PASSWORD={ADMIN_PASSWORD}",
            "-e",
            "LDAP_CUSTOM_SCHEMA_DIR=/schemas",
            "-e",
            "LDAP_SKIP_DEFAULT_TREE=yes",
            "-e",
            "LDAP_EXTRA_SCHEMAS=cosine,inetorgperson,nis",
            "-e",
            "LDAP_CONFIG_ADMIN_ENABLED=yes",
            "-e",
            "LDAP_CONFIG_ADMIN_USERNAME=admin",
            "-e",
            f"LDAP_CONFIG_ADMIN_PASSWORD={CONFIG_PASSWORD}",
            "-v",
            f"{SCHEMAS}:/schemas:ro",
            "-v",
            f"{name}:/bitnami/openldap",
            IMAGE,
        )
        wait_ready(name, loaded=False)
        tune(name, args.indexes)
        started = time.monotonic()
        uri = f"ldap://127.0.0.1:{port}"
        if args.load == "slapadd":
            docker("stop", name)
            docker(
                "run",
                "--rm",
                "--volumes-from",
                name,
                "-v",
                f"{ldif}:/tmp/bench.ldif:ro",
                "--entrypoint",
                f"{BIN}/sbin/slapadd",
                IMAGE,
                "-F",
                "/bitnami/openldap/slapd.d",
                "-b",
                demo.BASE,
                "-q",
                "-l",
                "/tmp/bench.ldif",  # noqa: S108
            )
            docker("start", name)
        else:
            subprocess.run(  # noqa: S603
                ["ldapadd", "-x", "-H", uri, "-D", ADMIN_DN, "-w", ADMIN_PASSWORD, "-f", str(ldif)],  # noqa: S607
                check=True,
                capture_output=True,
            )
        wait_ready(name, loaded=True)
        loaded = time.monotonic() - started
        version = docker("exec", name, "slapd", "-VV", check=False)
        banner = (version.stdout + version.stderr).replace("\n", " ")
        return {
            "name": name,
            "uri": uri,
            "bind_dn": ADMIN_DN,
            "bind_password": ADMIN_PASSWORD,
            "base_dn": demo.BASE,
            "server": f"{IMAGE} ({banner.split('$')[1].strip() if '$' in banner else 'slapd'})",
            "indexes": args.indexes,
            "entries": entries,
            "load_seconds": round(loaded, 1),
        }
    except BaseException:
        remove(name)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run(args: argparse.Namespace, extra: list[str]) -> int:
    info = up(args)
    try:
        command = [
            sys.executable,
            str(Path(__file__).with_name("bench.py")),
            "--backend",
            "ldap",
            "--users",
            str(args.users),
            "--ldap-uri",
            str(info["uri"]),
            "--bind-dn",
            str(info["bind_dn"]),
            "--bind-password",
            str(info["bind_password"]),
            "--server",
            str(info["server"]),
            "--indexes",
            str(info["indexes"]),
            *extra,
        ]
        return subprocess.run(command, check=False).returncode  # noqa: S603
    finally:
        remove(str(info["name"]))


def dataset_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--indexes", choices=("default", "tuned"), default="default")
    parser.add_argument("--load", choices=("slapadd", "ldapadd"), default="slapadd")
    parser.add_argument("--port", type=int, default=0, help="host port (default: a free one)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dataset_options(sub.add_parser("up", help="start a server and load the dataset"))
    sub.add_parser("down", help="remove a server").add_argument("name")
    dataset_options(sub.add_parser("run", help="start a server, run bench.py on it, remove it"))
    args, extra = parser.parse_known_args()
    if args.command == "up":
        print(json.dumps(up(args)))
    elif args.command == "run":
        return run(args, [a for a in extra if a != "--"])
    else:
        remove(args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
