COMPOSE      := docker compose
COMPOSE_DEV  := docker compose -f docker-compose.yml -f compose.dev.yml

.PHONY: help up down dev logs ps migrate deploy rollback test web-test web-lint openapi lint format audit

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

# Deploy images built by CI (README section 11). `up` runs `migrate` before api/workers start.
deploy:  ## Deploy CI images: make deploy TAG=<git-sha>
	@test -n "$(TAG)" || { echo "usage: make deploy TAG=<git-sha>"; exit 1; }
	IMAGE_TAG=$(TAG) $(COMPOSE) pull
	IMAGE_TAG=$(TAG) $(COMPOSE) up -d --no-build --wait
	@echo "$$(date -u +%FT%TZ) $(TAG)" >> .deploy-history
	@echo "Deployed $(TAG). Earlier deploys are listed in .deploy-history"

rollback:  ## Roll back: make rollback TAG=<previous-sha> (see .deploy-history)
	@$(MAKE) --no-print-directory deploy TAG=$(TAG)

test:  ## Run backend and agent tests
	cd backend && uv run pytest -q . ../agent/tests

web-test:  ## Run frontend unit tests
	cd frontend && npm test

web-lint:  ## Check frontend formatting and that it builds
	cd frontend && npm run format:check && npm run build

openapi:  ## Regenerate frontend/openapi.json after changing the API
	cd backend && uv run python -m app.openapi_export ../frontend/openapi.json

lint:  ## Lint and check formatting
	cd backend && uv run ruff check . ../agent && uv run ruff format --check . ../agent

format:  ## Auto-format backend code
	cd backend && uv run ruff check --fix . && uv run ruff format .

audit:  ## Audit dependencies for known vulnerabilities
	cd backend && uv export --frozen --no-dev --no-hashes -o /tmp/requirements.txt && uv run pip-audit -r /tmp/requirements.txt
