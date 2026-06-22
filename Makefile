# ---------------------------------------------------------------------------
# Knesset OSINT — ops convenience targets.
#
# Cross-shell-simple: every recipe is a single command line so it behaves the
# same under bash, sh, PowerShell (via `make` from Git Bash / WSL / choco make),
# and CI. No shell loops, no multi-line heredocs.
#
# Two execution surfaces:
#   * Stack targets (up/down/logs/migrate/ingest/smoke) drive docker compose.
#   * Local dev targets (test/fmt) use the project venv python directly so you
#     get fast feedback without rebuilding the image.
#
# Override knobs on the command line, e.g.:
#   make ingest PERSON_ID=30    # ingest a different politician
#   make logs SERVICE=postgres  # tail one service
# ---------------------------------------------------------------------------

# docker compose v2 ("docker compose") is the default; override if you still use
# the legacy v1 binary:  make up COMPOSE="docker-compose"
COMPOSE ?= docker compose

# Pilot politician (Netanyahu, KNS_Person.Id=965). Override to ingest others.
PERSON_ID ?= 965

# Which service to tail with `make logs`. Empty = all services.
SERVICE ?=

# Local venv python (used for test/fmt without touching Docker). On Windows this
# is the Scripts path; override on POSIX with:  make test PYTHON=.venv/bin/python
PYTHON ?= .venv/Scripts/python.exe

.PHONY: up down logs migrate ingest test smoke fmt help

help: ## Show this help.
	@echo "Targets: up down logs migrate ingest test smoke fmt"

up: ## Build images and start the full stack (postgres, neo4j, api) detached.
	$(COMPOSE) up --build -d

down: ## Stop and remove containers (named volumes are preserved).
	$(COMPOSE) down

logs: ## Tail container logs. Use SERVICE=postgres|neo4j|api to scope.
	$(COMPOSE) logs -f $(SERVICE)

migrate: ## Apply Alembic migrations inside a one-off api container.
	$(COMPOSE) run --rm api alembic upgrade head

ingest: ## Run the CLI ingest for a politician (default PERSON_ID=965, Netanyahu).
	$(COMPOSE) run --rm api knesset-osint ingest person --person-id $(PERSON_ID)

test: ## Run the test suite locally via the project venv.
	$(PYTHON) -m pytest

smoke: ## Liveness check: confirm the running API answers HTTP on localhost:8000.
	$(PYTHON) -c "exec('import urllib.request,urllib.error\ntry:\n urllib.request.urlopen(\'http://localhost:8000/\',timeout=10); print(\'API up (2xx)\')\nexcept urllib.error.HTTPError as e:\n print(\'API up (HTTP %s)\'%e.code)\nexcept Exception as e:\n raise SystemExit(\'API not reachable: %s\'%e)')"

fmt: ## Format + lint-fix the codebase locally with ruff.
	$(PYTHON) -m ruff format src tests && $(PYTHON) -m ruff check --fix src tests
