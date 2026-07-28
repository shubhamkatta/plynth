.PHONY: help install dev up down logs shell migrate revision seed test lint fmt typecheck openapi

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## install python deps into the active venv
	pip install -e ".[dev]"

dev: ## run api with autoreload
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

up: ## docker compose up (detached)
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

shell:
	docker compose exec api /bin/bash

migrate: ## apply migrations
	docker compose exec api alembic upgrade head

openapi: ## Regenerate docs/openapi.json from the live FastAPI app
	python3 scripts/dump_openapi.py
	@echo "Wrote docs/openapi.json ($$(wc -c < docs/openapi.json) bytes)"

revision: ## autogenerate migration: make revision m="add x"
	docker compose exec api alembic revision --autogenerate -m "$(m)"

seed: ## load seed data (default plans + admin tenant)
	docker compose exec api python -m scripts.seed

test:
	pytest -q

lint:
	ruff check .

fmt:
	ruff format .
	ruff check --fix .

typecheck:
	mypy app

# ---- Production (DigitalOcean droplet: docker-compose + Caddy) -------------
# These targets run ON the droplet, from the repo root. Migrations and seeding
# are separate targets — run `prod-migrate` (and `prod-seed` if needed) after
# `deploy`. See docs/deploy-digitalocean.md.
deploy: ## pull + rebuild the prod stack on the droplet (run migrate/seed separately)
	git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

prod-shell: ## shell into the running api container on the droplet
	docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api /bin/bash

prod-seed: ## seed default product + plans + admin against the prod DB
	docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api python -m scripts.seed

prod-migrate: ## run alembic upgrade head against the prod DB
	docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic upgrade head
