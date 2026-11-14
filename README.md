# Heracles

Heracles is a web console for managing an LDAP directory: users, groups, roles,
departments, delegated administration, and enterprise services (POSIX, SSH,
sudo, mail, DNS, DHCP, systems inventory, password policies...). It runs next to
your existing LDAP server and ships its own LDAP schema (`hrc*` classes).

* **Backend**: Python 3.12+, FastAPI, python-ldap (`backend/`)
* **Frontend**: React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS v4 (`frontend/`)

Status: early development.

## Quick start

You need Docker and an LDAP server you can reach (with the Heracles schema loaded,
or the setup will export it for you).

```bash
docker compose -f deploy/production/compose.yml up -d --build
docker compose -f deploy/production/compose.yml logs heracles   # prints the setup token
# open http://localhost:8420 and paste the token
```

With no configuration file, Heracles starts in setup mode. The console asks for the
directory (it tests the connection and checks the schema), the first administrator and
the plugins to enable, then writes its configuration to the data volume and switches to
normal mode without a restart. Log in with the administrator you just created.

Prefer a terminal? `heracles init` asks the same questions (or takes flags with `--yes`:
`--uri --bind-dn --bind-password-file --base-dn --admin-uid --admin-password-file
--plugins core|all|a,b --output PATH`). To write the configuration by hand, start from
`deploy/production/heracles.example.yaml`.

Put a TLS-terminating reverse proxy in front of the console for anything but a trial.
State that is not in the directory (sessions, login throttling, recovery tokens, second
factors) lives in the application database (SQLite in the data volume by default), so
`heracles serve --workers N` can run several processes once the console is configured.

## Configuration

Every setting is described, commented, in `deploy/production/heracles.example.yaml`.
The configuration file is `$HERACLES_CONFIG` (or `--config`); `$HERACLES_DATA_DIR` holds
the application database. `heracles --help` lists the commands: `serve`, `init`, `worker`,
`check`, `fix`, `create-admin`, `schema export`, `dns`, `migrate-directory`.

## Development

```bash
make install   # backend (uv) + frontend (pnpm) dependencies
make dev       # whole stack: OpenLDAP + API + DNS + SMB/FTP/DHCP containers, UI on http://localhost:5173
```

Log in with `alice` / `alice-secret` (real OpenLDAP container, seed in
`deploy/ldap/seed.ldif`). `make dev-down` stops the containers and keeps their data.
The API runs in a container, so backend edits need `make dev` again; the UI hot-reloads.
No Docker? `make dev-demo` runs the in-memory demo directory instead (no LDAP;
`admin` / `heracles`).

The dev directory also feeds three real servers (build files in `deploy/dev/`), so the
plugins of the console drive something observable. They read exactly the standard LDAP
schema the console writes (`deploy/ldap/schema/`), with the well-known dev credentials
(`ldap` / `admin` / `admin`):

| Service | Host port | What it serves |
|---|---|---|
| `smb` | 127.0.0.1:445 | SMB shares for the accounts of `ou=people` (LDAP passdb, domain `HERACLES`) |
| `ftp` | 127.0.0.1:2121, passive 30000-30009 | FTP accounts with `FTPStatus` enabled, home `homeDirectory` |
| `dhcp` | — (isolated compose network 192.168.220.0/24) | The `dhcpService`/`dhcpSubnet`/`dhcpHost` entries under `ou=dhcp` |

Enable SMB or FTP for a user in the console (user → SMB / FTP tab, with a password),
then try it from the host or in a container:

```bash
smbclient -L //127.0.0.1 -U alice%alice-secret        # or: docker compose -f deploy/docker-compose.yml exec smb smbclient -L //localhost -U alice%alice-secret
smbclient //127.0.0.1/shared -U alice%alice-secret -c ls
lftp -u alice,alice-secret 127.0.0.1:2121 -e "ls; bye"   # or: docker compose ... exec ftp lftp -u alice,alice-secret 127.0.0.1 -e "ls; bye"
make dhcp-test                                          # one-shot client on the isolated network
```

`make dhcp-test` asks the `dhcp` container for a lease from a throwaway container with a
fixed MAC address; the directory reserves its address (`cn=dhcp-client`, `192.168.220.50`).
Nothing is published on the host for DHCP, so it cannot hand out leases on your LAN.
The servers read the directory when they start (the DHCP server renders `dhcpd.conf` from
the directory when it starts, the FTP server creates the home on first login): recreate
the stack after changing schema LDIFs, and `docker compose -f deploy/docker-compose.yml
--profile dev restart dhcp` after editing the DHCP configuration in the console.


Other useful targets (`make help` lists them all):

| Target | What it does |
|---|---|
| `make dev-demo` | in-memory demo directory (no LDAP) + UI |
| `make dev-down` | stop the dev containers, keep the LDAP data volume |
| `make dhcp-test` | ask the dev DHCP server for a lease (isolated compose network) |
| `make demo` | build the UI and serve everything from the demo backend |
| `make dns-demo` | serve the demo directory's DNS zones on port 5353 |
| `make dev-mock` | UI only, with the in-browser mock API |
| `make test` / `make check` | tests / lint + types + tests |
| `make bench USERS=5000` | latency and LDAP round trips per API endpoint on a large demo directory |
| `make e2e-replicas` | browser e2e tests against two replicas behind a load balancer (own compose project, ports 8421/8422/8430) |
| `make ldap-up` | start the test OpenLDAP server (port 1389) |
| `make serve CONFIG=heracles.yaml` | run against a real directory |


The zones stored by the DNS plugin can be served authoritatively: `make dns-demo`
answers for the demo zone on port 5353 (`dig @127.0.0.1 -p 5353 www.heracles.test`),
and `make dev` starts the compose stack's `dns` service with the seed zone
`heracles.test` on port 15353 (`dig @127.0.0.1 -p 15353 www.heracles.test`).
An existing LDAP volume predates that seed: drop it with
`docker compose -f deploy/docker-compose.yml down -v` to load it.

Heracles needs its own LDAP schema on the directory: `heracles schema export` prints it.
