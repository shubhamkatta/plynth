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

# ---- Fly.io ---------------------------------------------------------------
deploy: ## fly deploy (runs alembic upgrade head as release_command)
	fly deploy

logs: ## tail fly logs (combined api + worker)
	fly logs

prod-shell: ## ssh into a running api machine
	fly ssh console

prod-seed: ## seed default product + plans + admin against the prod DB
	fly ssh console -C "python -m scripts.seed"

prod-migrate: ## run alembic upgrade head manually (release_command does this on deploy)
	fly ssh console -C "alembic upgrade head"
