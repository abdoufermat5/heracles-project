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
make dev       # demo API on :8420 (auto-reload) + UI on http://localhost:5173
```

Log in with `admin` / `heracles` (in-memory demo directory, no LDAP needed).
Other useful targets (`make help` lists them all):

| Target | What it does |
|---|---|
| `make demo` | build the UI and serve everything from the demo backend |
| `make dev-mock` | UI only, with the in-browser mock API |
| `make test` / `make check` | tests / lint + types + tests |
| `make ldap-up` | start the test OpenLDAP server (port 1389) |
| `make serve CONFIG=heracles.yaml` | run against a real directory |

Heracles works on directories that provide its compatibility LDAP schema.
