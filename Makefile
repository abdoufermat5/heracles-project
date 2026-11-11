# Heracles — developer shortcuts. Run `make` or `make help` to list targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
FRONTEND := frontend
COMPOSE  := docker compose -f deploy/docker-compose.yml

HOST ?= 127.0.0.1
PORT ?= 8420
UI_PORT ?= 5173
DNS_PORT ?= 15353
CONFIG ?= $(HERACLES_CONFIG)

.PHONY: help install install-backend install-frontend \
        dev dev-demo dev-down dev-mock backend frontend demo build serve dns-demo \
        test test-backend test-frontend lint lint-backend lint-frontend \
        format typecheck check bench ldap-up ldap-down ldap-logs test-integration e2e e2e-ui e2e-down schema third-party-schema clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} \
	     /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo
	@echo "  Variables: HOST=$(HOST) PORT=$(PORT) UI_PORT=$(UI_PORT) CONFIG=<config file>"
	@echo

# --------------------------------------------------------------- install

install: install-backend install-frontend ## Install backend and frontend dependencies

install-backend: ## Install backend dependencies (uv)
	cd $(BACKEND) && uv sync

install-frontend: ## Install frontend dependencies (pnpm)
	cd $(FRONTEND) && pnpm install

# ------------------------------------------------------------------- run

dev: ## Whole stack: OpenLDAP + API + DNS containers, Vite dev server on the host
	@echo "→ API http://$(HOST):$(PORT) (container, real LDAP) · DNS 127.0.0.1:$(DNS_PORT) · UI http://localhost:$(UI_PORT) · login alice / alice-secret"
	@echo "  DNS zones of the directory: dig @127.0.0.1 -p $(DNS_PORT) www.heracles.test"
	@echo "  the containers stay up after this exits; stop them with \`make dev-down\`"
	$(COMPOSE) --profile dev up -d --build --wait
	@trap 'kill 0' INT TERM EXIT; \
	  (cd $(FRONTEND) && VITE_API_MOCK=false HERACLES_API_URL=http://$(HOST):$(PORT) \
	      pnpm exec vite --port $(UI_PORT)) & \
	  wait

dev-demo: ## Demo backend (in-memory directory, auto-reload) + Vite dev server
	@echo "→ API http://$(HOST):$(PORT)  ·  UI http://localhost:$(UI_PORT)  ·  login admin / heracles"
	@trap 'kill 0' INT TERM EXIT; \
	  (cd $(BACKEND) && uv run uvicorn heracles.server:build_demo_app --factory --reload \
	      --host $(HOST) --port $(PORT)) & \
	  (cd $(FRONTEND) && VITE_API_MOCK=false HERACLES_API_URL=http://$(HOST):$(PORT) \
	      pnpm exec vite --port $(UI_PORT)) & \
	  wait

dev-down: ## Stop the dev containers (the LDAP data volume is kept)
	$(COMPOSE) --profile dev down

dev-mock: ## Frontend only, with the in-browser mock API (no backend)
	cd $(FRONTEND) && VITE_API_MOCK=true pnpm exec vite --port $(UI_PORT)

backend: ## Demo backend only, with auto-reload
	cd $(BACKEND) && uv run uvicorn heracles.server:build_demo_app --factory --reload \
	  --host $(HOST) --port $(PORT)

frontend: ## Vite dev server only, proxied to the backend on $(PORT)
	cd $(FRONTEND) && VITE_API_MOCK=false HERACLES_API_URL=http://$(HOST):$(PORT) \
	  pnpm exec vite --port $(UI_PORT)

build: ## Build the frontend (frontend/dist)
	cd $(FRONTEND) && pnpm build

demo: build ## Build the UI and serve everything from the demo backend
	@echo "→ http://$(HOST):$(PORT)  ·  login admin / heracles"
	cd $(BACKEND) && uv run heracles serve --demo --static ../$(FRONTEND)/dist \
	  --host $(HOST) --port $(PORT)

serve: ## Production server on a real directory (CONFIG=path/to/heracles.yaml)
	@test -n "$(CONFIG)" || { echo "Set CONFIG=path/to/heracles.yaml (or HERACLES_CONFIG)"; exit 1; }
	cd $(BACKEND) && uv run --extra ldap heracles serve --config "$(abspath $(CONFIG))" \
	  --host $(HOST) --port $(PORT)

dns-demo: ## Serve the demo directory's DNS zones on port 5353
	cd $(BACKEND) && uv run --extra dns heracles dns --demo --port 5353

# --------------------------------------------------------------- quality

test: test-backend test-frontend ## Run all tests

test-backend: ## Backend tests (pytest)
	cd $(BACKEND) && uv run pytest -q

test-frontend: ## Frontend tests (vitest)
	cd $(FRONTEND) && pnpm test --run

lint: lint-backend lint-frontend ## Lint backend and frontend

lint-backend: ## ruff check + format check
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .

lint-frontend: ## ESLint (needs frontend/eslint.config.js)
	cd $(FRONTEND) && pnpm lint

format: ## Format backend code (ruff)
	cd $(BACKEND) && uv run ruff format . && uv run ruff check --fix .

typecheck: ## pyright (strict) + tsc
	cd $(BACKEND) && uv run pyright
	cd $(FRONTEND) && pnpm exec tsc -b

check: lint-backend typecheck test ## Everything CI runs (except frontend lint)

bench: ## API latency and LDAP round trips per endpoint on a large demo directory (USERS=5000)
	cd $(BACKEND) && uv run python scripts/bench.py --users $(or $(USERS),5000)

# ------------------------------------------------------------ test LDAP

ldap-up: ## Start the test OpenLDAP server (port 1389)
	$(COMPOSE) up -d

ldap-down: ## Stop the test OpenLDAP server
	$(COMPOSE) down

ldap-logs: ## Follow the test OpenLDAP logs
	$(COMPOSE) logs -f

test-integration: ## python-ldap integration tests (in a container, against the test LDAP)
	$(COMPOSE) --profile e2e run --rm --build integration

e2e: ## Build and start OpenLDAP + Heracles containers, run the end-to-end tests
	$(COMPOSE) --profile e2e up -d --build --wait heracles
	cd $(BACKEND) && HERACLES_E2E_URL=http://localhost:8420 uv run pytest -q -m e2e tests/e2e
	$(COMPOSE) --profile e2e run --rm integration
	cd $(FRONTEND) && HERACLES_E2E_URL=http://localhost:8420 pnpm exec playwright test

e2e-ui: ## Browser end-to-end tests only, against the running stack (make dev or make e2e)
	cd $(FRONTEND) && HERACLES_E2E_URL=http://localhost:$(PORT) pnpm exec playwright test

e2e-down: ## Stop the end-to-end stack and drop its LDAP data
	$(COMPOSE) --profile e2e down -v

schema: ## Regenerate the Heracles LDAP schema files (deploy/ldap/schema/heracles.{ldif,schema})
	cd backend && uv run heracles schema export --format ldif -o ../deploy/ldap/schema/heracles.ldif
	cd backend && uv run heracles schema export --format schema -o ../deploy/ldap/schema/heracles.schema

third-party-schema: ## Convert third-party .schema files to LDIF for the test LDAP (SCHEMAS="a.schema b.schema")
	@test -n "$(SCHEMAS)" || { echo 'Usage: make third-party-schema SCHEMAS="path/sudo.schema ..."'; exit 1; }
	i=0; for s in $(SCHEMAS); do i=$$((i+1)); \
	  python3 deploy/ldap/schema2ldif.py "$$s" -o deploy/ldap/schema --prefix "$$(printf '%02d' $$i)-"; done

# ----------------------------------------------------------------- clean

clean: ## Remove caches and build output
	rm -rf $(FRONTEND)/dist $(FRONTEND)/*.tsbuildinfo
	find $(BACKEND) -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \
	  -o -name .hypothesis \) -prune -exec rm -rf {} +
