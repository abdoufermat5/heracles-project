# syntax=docker/dockerfile:1
# Multi-stage build: frontend assets, Python dependencies, slim runtime.

# --- frontend build (placeholder until the SPA lands) -------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/ ./
RUN if [ -f package.json ]; then \
      corepack enable && pnpm install --frozen-lockfile && pnpm build; \
    else \
      mkdir -p dist; \
    fi

# --- python build ---------------------------------------------------------------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libldap2-dev libsasl2-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --extra ldap --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --extra ldap

# --- runtime --------------------------------------------------------------------
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libldap2 libsasl2-2 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --create-home heracles
WORKDIR /app
COPY --from=build /app/backend/.venv /app/.venv
COPY --from=frontend /app/frontend/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" HERACLES_STATIC_DIR=/app/static
USER heracles
EXPOSE 8000
CMD ["uvicorn", "heracles.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
