DC = docker compose
APP = $(DC) exec web python manage.py
PY ?= .venv/bin/python
MANAGE = $(PY) manage.py

.PHONY: up down logs ps seed superuser sync shell gmail-auth \
        install db run worker migrations migrate test lint fmt lock

# --- Docker: the whole stack (db + web + worker), same image as the server ----------
up:                 ## build and start everything on http://localhost:8000
	$(DC) up -d --build

down:
	$(DC) down

logs:
	$(DC) logs -f --tail=100 web worker

ps:
	$(DC) ps

seed:               ## demo cards; creates admin/admin if there are no users
	$(APP) seed_demo

superuser:
	$(APP) createsuperuser

sync:               ## run Odoo, Gmail and skills sync once and print the result
	$(APP) sync_now

shell:
	$(APP) shell

gmail-auth:         ## one-time Gmail consent; add ARGS=--print to get GMAIL_TOKEN_JSON for a server
	$(DC) run --rm -p 127.0.0.1:8085:8085 web python manage.py gmail_auth --bind 0.0.0.0 --no-browser $(ARGS)

# --- Local Python: development and tests (Postgres from `make db`) -------------------
install:            ## venv + dependencies (Ubuntu/WSL: sudo apt install python3-venv first)
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

db:                 ## only Postgres in Docker, on localhost:5432
	$(DC) up -d db

run:                ## dev server with auto-reload on :8000 (stop the web container first)
	$(MANAGE) runserver

worker:
	$(MANAGE) procrastinate worker

migrations:
	$(MANAGE) makemigrations

migrate:
	$(MANAGE) migrate

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

lock:               ## re-pin requirements.lock after changing dependencies in pyproject.toml
	rm -rf .lockvenv && python3 -m venv .lockvenv
	.lockvenv/bin/pip install -q .
	.lockvenv/bin/pip freeze --exclude workboard > requirements.lock
	rm -rf .lockvenv build *.egg-info
