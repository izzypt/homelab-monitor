COMPOSE      := docker compose
COMPOSE_DEV  := docker compose -f docker-compose.yml -f compose.dev.yml

.PHONY: help up down dev logs ps migrate test lint format audit

help:  ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up:  ## Start the stack (builds the image locally)
	$(COMPOSE) up -d --build

down:  ## Stop the stack (keeps the database volume)
	$(COMPOSE) down

dev:  ## Start with hot reload, API on 127.0.0.1:8000
	$(COMPOSE_DEV) up --build

logs:  ## Follow logs
	$(COMPOSE) logs -f --tail=100

ps:  ## Show service status
	$(COMPOSE) ps

migrate:  ## Run database migrations
	$(COMPOSE) run --rm migrate

test:  ## Run backend tests
	cd backend && uv run pytest -q . ../agent/tests

lint:  ## Lint and check formatting
	cd backend && uv run ruff check . ../agent && uv run ruff format --check . ../agent

format:  ## Auto-format backend code
	cd backend && uv run ruff check --fix . && uv run ruff format .

audit:  ## Audit dependencies for known vulnerabilities
	cd backend && uv export --frozen --no-dev --no-hashes -o /tmp/requirements.txt && uv run pip-audit -r /tmp/requirements.txt
