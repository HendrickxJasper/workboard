PY ?= .venv/bin/python
MANAGE = $(PY) manage.py

.PHONY: install up down run worker migrations migrate shell test lint fmt seed gmail-auth sync superuser

install:            ## create venv and install deps
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

up:                 ## start Postgres
	docker compose up -d db

down:
	docker compose down

run:                ## dev server on :8000
	$(MANAGE) runserver

worker:             ## Procrastinate worker (sync, Claude runs, periodic jobs)
	$(MANAGE) procrastinate worker

migrations:
	$(MANAGE) makemigrations

migrate:
	$(MANAGE) migrate

shell:
	$(MANAGE) shell

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

seed:               ## demo cards, no credentials needed
	$(MANAGE) seed_demo

gmail-auth:         ## one-time OAuth consent in the browser
	$(MANAGE) gmail_auth

sync:               ## run Odoo + Gmail sync once in the foreground
	$(MANAGE) sync_now

superuser:
	$(MANAGE) createsuperuser
