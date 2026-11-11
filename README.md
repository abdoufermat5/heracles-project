# Heracles

Heracles is a web console for managing an LDAP directory: users, groups, roles,
departments, delegated administration, and enterprise services (POSIX, SSH,
sudo, mail, DNS, DHCP, systems inventory, password policies…).

* **Backend**: Python 3.12+, FastAPI, python-ldap — `backend/`
* **Frontend**: React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS v4 — `frontend/`

Status: early development.

## Quick start

```bash
make install   # backend (uv) + frontend (pnpm) dependencies
make dev       # whole stack: OpenLDAP + API containers, UI on http://localhost:5173
```

Log in with `alice` / `alice-secret` (real OpenLDAP container, seed in
`deploy/ldap/seed.ldif`). `make dev-down` stops the containers and keeps their data.
The API runs in a container, so backend edits need `make dev` again; the UI hot-reloads.
No Docker? `make dev-demo` runs the in-memory demo directory instead (no LDAP;
`admin` / `heracles`).
Other useful targets (`make help` lists them all):

| Target | What it does |
|---|---|
| `make dev-demo` | in-memory demo directory (no LDAP) + UI |
| `make dev-down` | stop the dev containers, keep the LDAP data volume |
| `make demo` | build the UI and serve everything from the demo backend |
| `make dns-demo` | serve the demo directory's DNS zones on port 5353 |
| `make dev-mock` | UI only, with the in-browser mock API |
| `make test` / `make check` | tests / lint + types + tests |
| `make bench USERS=5000` | latency and LDAP round trips per API endpoint on a large demo directory |
| `make ldap-up` | start the test OpenLDAP server (port 1389) |
| `make serve CONFIG=heracles.yaml` | run against a real directory |

Production state that is not in the directory (sessions, login throttling,
recovery tokens, second factors) lives in the SQLite application database, so
`heracles serve --workers N` can run several processes sharing it.

The zones stored by the DNS plugin can be served authoritatively: `make dns-demo`
answers for the demo zone on port 5353 (`dig @127.0.0.1 -p 5353 www.heracles.test`),
and the `dns` service of the compose stack publishes the test directory's zones
on port 15353.

Heracles works on directories that provide its compatibility LDAP schema.
