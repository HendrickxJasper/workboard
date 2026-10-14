# Workboard

A local, single-user work dashboard. One kanban board over your Odoo tasks, tickets and activities, your Gmail inbox and your own to-dos. Claude triages every card, rates how much it can help, proposes the next step, and drafts actions. Nothing touches Odoo or Gmail until you approve it.

First built for Scrollit. Everything company-specific (Odoo URL, support team, skills repo, names) is configured in `.env`, so it works for any company that uses Odoo 19+ and Google Workspace.

![Board](docs/board.png)

## What it does

- **One board, six columns**: Inbox → Triaged → AI drafted → Waiting on me → Waiting on others → Done. Drag cards between columns (SortableJS + HTMX).
- **Running vs idle at a glance.** A card is *running* while Claude works on it (the badge shows the live step, e.g. "Looking up res.partner in Odoo") or while an Odoo timer runs on its task or ticket. A card is *idle* after `IDLE_AFTER_DAYS` without activity: dashed, muted, "Idle 6d". The toolbar has a Running/Idle filter and live counters.
- **Claude triage** for every new or changed card: classification, customer, urgency, AI-assist score (0–3), next step, and proposed actions. Claude can only *read* (Odoo lookups on an allowlist of models, team skills). It cannot write.
- **Approve, edit or reject actions** in the card drawer: create a helpdesk ticket, post an internal note on it, create a Gmail reply draft, or create a to-do. Payloads are editable JSON before you approve.
- **Misrouted support mail flow**: a customer mails you instead of support → Claude proposes a ticket for the customer's partner (assigned to `ODOO_SUPPORT_TEAM_ID`), an internal note with its analysis and a proposed fix for a colleague, and a reply draft that quotes the new ticket number.
- **Team skills**: clones your skills repo (e.g. `scrollit/claude-skills`, Claude Code plugin marketplace layout), indexes every `SKILL.md`, and lets Claude load the relevant one during triage. Usage is counted per skill.

## Quick start (Docker)

Needs Docker with Compose and `make`. On Windows, run it in WSL with Docker Desktop's WSL integration turned on for your distro.

```bash
cp .env.example .env         # fill in what you have; the board works without any keys
make up                      # builds the image, starts db + web + worker
make seed                    # optional: demo cards, creates admin/admin if there are no users
make superuser               # or create your own login
```

Open http://localhost:8000. `make logs` follows web and worker; `make sync` runs Odoo, Gmail and skills sync once and prints the result, which is handy the first time.

The containers are the same image the server runs. Migrations run in the web container's entrypoint before gunicorn starts; the worker never migrates.

### Local Python instead (for development)

Auto-reload, debugger, tests. On Ubuntu/WSL first: `sudo apt install python3-venv`.

```bash
make install                 # venv + dependencies
make db                      # only Postgres in Docker, on localhost:5432
make migrate && make run     # dev server on :8000 (stop the web container first: docker compose stop web)
make worker                  # second terminal
make test && make lint
```

## Configuration

| What | How |
|---|---|
| **Odoo** (19+, JSON-2 API) | In Odoo: *Preferences → Account Security → New API Key*. Set `ODOO_URL`, `ODOO_DB`, `ODOO_API_KEY`, `ODOO_LOGIN`. The key acts as your user. |
| **Support team** | `ODOO_SUPPORT_TEAM_ID` = the `helpdesk.team` id that misrouted mails should go to. |
| **Gmail** | Google Cloud console → enable Gmail API → OAuth client of type *Desktop app* → save the JSON as `secrets/gmail_client.json` → `make gmail-auth` → open the printed URL and approve. The callback comes back on http://localhost:8085. Scopes: read and compose drafts. It never sends. |
| **Claude** | `ANTHROPIC_API_KEY`, optionally `CLAUDE_MODEL` (default `claude-sonnet-5-5`). Use your company's org account. Card content (mails, tickets) is sent to the API. |
| **Skills repo** | `SKILLS_REPO_URL`, plus `SKILLS_REPO_TOKEN` for a private repo (GitHub fine-grained token with read access to *Contents* of that one repo). The token is sent as a header per git call and never stored. Pulled fast-forward only every 30 min; local edits block the pull and are reported, never overwritten. |
| **Behaviour** | `IDLE_AFTER_DAYS` (3), `AGENT_RUN_TIMEOUT_MIN` (15), `AUTO_TRIAGE` (true), `GMAIL_QUERY`. |

## Running it on a server

The repo ships a Kamal setup that follows the usual Scrollit deploy layout: `config/deploy.yml` (roles `web` and `worker`, Postgres accessory, `/healthz` health check, a `workboard_data` volume for the Gmail token and skills clone) and `config/deploy.office.yml` for the office server over Tailscale.

1. Fill in the `CHANGE-ME` values in `config/deploy.yml` (Odoo URL/db) and `config/deploy.office.yml` (Tailscale host, browser hostname).
2. Get the Gmail token on your laptop: `make gmail-auth ARGS=--print`. Copy the printed JSON line; it becomes the `GMAIL_TOKEN_JSON` secret. The server writes it to its data volume on first use and keeps the refreshed token there.
3. Export the secrets listed in `.kamal/secrets` in your shell (or wire them to your password manager). `WORKBOARD_DATABASE_URL` is `postgres://workboard:<POSTGRES_PASSWORD>@workboard-db:5432/workboard`.
4. `kamal setup -d office` the first time, then `kamal deploy -d office`. The entrypoint creates the `jasper` login from `DJANGO_SUPERUSER_PASSWORD` on first boot.

**Reaching it from anywhere.** The board shows client mails and tickets and can create drafts and tickets, so keep it off the open internet:
- *Tailscale only* (simplest): open it on any device that's on your tailnet. Nothing is public.
- *Cloudflare Tunnel + Cloudflare Access*: a normal https hostname, but only your Google login gets through. Then set `SECURE_COOKIES=true` and use the https origin in `CSRF_TRUSTED_ORIGINS`.

## Safety model

1. Claude's tools are read-only: `odoo_search_read` on an allowlist of models (max 20 rows), `read_skill`, `submit_triage`.
2. Claude's output is a *proposal*: rows in `ProposedAction`. Payloads are validated server-side.
3. Only an explicit **Approve** executes an action, in dependency order. Execution is idempotent.
4. Gmail actions create drafts only.

## How it's built

Django 5.2 · PostgreSQL · HTMX 2 · SortableJS · Procrastinate (Postgres-backed jobs, no Redis) · Anthropic Python SDK.

| App | Holds |
|---|---|
| `connector` | `Connection`, Odoo JSON-2 client, Gmail client, sync services and periodic tasks |
| `card` | `Client`, `Card`, board services (activity state, moving, upsert), board views |
| `agent` | `AgentRun`, `ProposedAction`, Claude triage loop, action validation and execution |
| `skill` | `SkillRepo`, `Skill`, clone/pull/index |

Business rules and the data model are in [`docs/analysis/workboard.md`](docs/analysis/workboard.md), including what v1 does differently from the analysis and what still needs checking against a real Odoo.

```bash
make test    # pytest: one test per business rule + smoke tests per URL
make lint    # ruff
```

## Roadmap

- **Phase 2**: retro when a card moves to Done → proposed skill changes → a branch and pull request on the shared skills repo, never a direct push.
- **Phase 3**: local files / Drive, reminders on to-dos, more action types, auto-approve rules.
