# syntax=docker/dockerfile:1
# Multi-stage build: frontend assets, Python dependencies, slim runtime.

# --- frontend build -------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/ ./
RUN npm install -g pnpm@11.22.0 && pnpm install --frozen-lockfile && pnpm build

# --- python build ---------------------------------------------------------------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libldap2-dev libsasl2-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --extra ldap --extra dns --extra postgres --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --extra ldap --extra dns --extra postgres --no-editable

# --- tests (python-ldap integration tests against the compose LDAP server) --------
FROM build AS test
RUN uv sync --frozen --extra ldap --extra dns --extra postgres
COPY backend/tests ./tests
ENV HERACLES_TEST_LDAP_URI=ldap://ldap:1389
CMD ["uv", "run", "--frozen", "--extra", "ldap", "--extra", "dns", "pytest", "-q", "-m", "integration", "-p", "no:cacheprovider"]

# --- runtime --------------------------------------------------------------------
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libldap2 libsasl2-2 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --create-home heracles \
 && install -d -o heracles -g heracles -m 0700 /var/lib/heracles
WORKDIR /app
COPY --from=build /app/backend/.venv /app/backend/.venv
COPY --from=frontend /app/frontend/dist /app/static
ENV PATH="/app/backend/.venv/bin:$PATH" HERACLES_CONFIG=/etc/heracles/heracles.yaml \
    HERACLES_DATA_DIR=/var/lib/heracles
# application database (second-factor registrations, ...): keep it on a volume
VOLUME ["/var/lib/heracles"]
USER heracles
EXPOSE 8420
HEALTHCHECK --interval=5s --timeout=3s --retries=20 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/readyz')"
# --with-worker runs the task scheduler (reminders, audit purge, ...) inside the server;
# several replicas are safe: a lease in the application database serialises the passes.
CMD ["heracles", "serve", "--host", "0.0.0.0", "--port", "8420", "--with-worker"]
