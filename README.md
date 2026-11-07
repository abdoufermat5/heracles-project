# Heracles

Heracles is a web console for managing an LDAP directory: users, groups, roles,
departments, delegated administration, and enterprise services (POSIX, SSH,
sudo, mail, DNS, DHCP, systems inventory, password policies…).

* **Backend**: Python 3.12+, FastAPI, python-ldap — `backend/`
* **Frontend**: React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS v4 — `frontend/`

Status: early development.

## Quick start (development)

```bash
docker compose -f deploy/docker-compose.yml up -d   # test LDAP server
cd backend && uv sync && uv run pytest
cd frontend && pnpm install && pnpm dev
```

Heracles works on directories that provide its compatibility LDAP schema.
