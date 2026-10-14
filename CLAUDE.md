# Workboard: notes for coding agents

Local Django + HTMX kanban over Odoo, Gmail and to-dos, with Claude triage. Read `docs/analysis/workboard.md` first: it has the data model, the numbered business rules (R1–R13) and the v1 deviations.

## Commands
- `make up` (Postgres in Docker), `make run`, `make worker`
- `make migrations`, `make migrate`, `make shell`, `make seed` (demo data)
- `make test` and `make lint` must pass before you say you are done.

## Conventions
- Apps per domain: `connector`, `card`, `agent`, `skill`. Every model inherits `core.BaseModel`.
- Business logic lives in `services.py` as plain functions with explicit arguments. Views are thin and never hold logic.
- Background work goes in `tasks.py` (Procrastinate). Tasks are idempotent. Services defer jobs through `core.enqueue.enqueue`, which runs after commit.
- HTMX: full pages extend `base.html`; HTMX responses render `templates/<app>/partials/`. The card face partial (`card/partials/card_face.html`) is the single source of truth for how a card looks. Reuse it, including as an out-of-band swap.
- Activity state (running/idle/active) is computed by `card.services.activity_state` and `Card.objects.running()/idle()`. Never store it.
- Settings come only from env vars (django-environ). Add new ones to `.env.example`.
- Don't add dependencies (Redis, Celery, a JS build, a SPA) without asking.

## Safety rules (do not weaken)
- Claude's tools in `agent/claude.py` are read-only. Never give Claude a tool that writes to Odoo, Gmail or git.
- Anything that changes the outside world is a `ProposedAction`, executed only from `agent.services.approve_action` after a user approves it.
- Gmail: drafts only. Shared skills repo: pull fast-forward only; changes go through pull requests (phase 2).

## Tests
- `tests/factories.py` has factory functions plus `FakeOdoo`, `FakeGmail` and `FakeLLM` (scripted `messages.create` responses). Use those; never call real services in tests.
- One test per business rule, named `test_rN_...`, plus a smoke test per URL.

## Never without approval
- Run anything against a real Odoo, Gmail or skills repo from a test or a script.
- Change secrets, `.env`, or delete data or migrations. Never edit a migration that is already on main.
