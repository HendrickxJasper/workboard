# Workboard (first built for Scrollit)

## Goal
A local, single-user dashboard for Jasper's work at Scrollit. It pulls Odoo tasks, tickets and activities, Gmail threads, files and loose to-dos into one kanban board. Claude triages every card, scores how much AI can help, proposes next steps and drafts actions (e.g. turn a misrouted customer mail into a helpdesk ticket with an analysis and proposed solution). The board shows at a glance which cards are **running** (Claude or a timer is working on them) and which are **idle**. Completed work feeds back into skills, kept in sync with the shared **Scrollit Skills repo** (functional analysis, technical analysis, devops, development, …).

It works when: every relevant item lands on the board within 5 minutes, triage proposals are accepted unchanged most of the time, and skill updates reach the shared repo as reviewable pull requests.

## Scope
- In (phase 1): Gmail + Odoo sync, unified cards, kanban with running/idle state, Claude triage, proposed actions with approval, the "misrouted support mail" flow.
- In (phase 2): Scrollit Skills repo sync, retro on Done, skill changes as PRs.
- In (phase 3): local files / Drive, manual to-dos with reminders, more action types.
- Out (later): auto-approve rules, multi-user, mobile UI, calendar.

## Assumptions
- Single user, runs locally (`make up`); no tenant scoping.
- Claude runs through the Claude Agent SDK (Python) inside Procrastinate workers, using Scrollit's org API key.
- The agent never writes to Odoo/Gmail/repos directly: it can only read and **propose**. Execution happens in services after approval.
- "Running" = an agent run is queued/running on the card, or an Odoo timer is running on the linked task/ticket. "Idle" = not running, not Done, and no activity for `IDLE_AFTER_DAYS` (default 3).
- Skills repo is a git repo with one folder per category containing `<slug>/SKILL.md`.

## Data model
All models inherit `core.BaseModel`.

| App | Model | Field | Type (Django) | Null/Default | Notes |
|---|---|---|---|---|---|
| connector | Connection | kind | CharField(choices) | – | gmail, odoo, files |
| | | name | CharField(100) | – | |
| | | config | JSONField | {} | non-secret settings (db, folder, label filters) |
| | | sync_cursor | JSONField | {} | Gmail historyId, Odoo write_date, … |
| | | last_sync_at | DateTimeField | null | |
| | | last_error | TextField | "" | shown on /connections/ |
| | | is_active | BooleanField | True | |
| card | Client | name | CharField(200) | – | |
| | | odoo_partner_id | IntegerField | null, unique | |
| | | email_domains | ArrayField(CharField) | [] | used to match senders |
| card | Card | source | CharField(choices) | – | gmail, odoo_task, odoo_ticket, odoo_activity, file, manual |
| | | connection | FK connector.Connection | null, PROTECT | null for manual |
| | | external_id | CharField(255) | "" | unique with source (when not manual) |
| | | external_url | URLField | "" | open in Odoo/Gmail |
| | | title | CharField(300) | – | |
| | | excerpt | TextField | "" | first ~1000 chars |
| | | client | FK card.Client | null, SET_NULL | |
| | | column | CharField(choices) | inbox | inbox, triaged, ai_drafted, waiting_me, waiting_others, done |
| | | position | PositiveIntegerField | 0 | order within column |
| | | urgency | CharField(choices) | normal | low, normal, high |
| | | due_date | DateField | null | |
| | | ai_assist_score | PositiveSmallIntegerField | null | 0 none … 3 Claude can draft it fully |
| | | next_step | TextField | "" | Claude's proposal |
| | | timer_running | BooleanField | False | mirrored from Odoo |
| | | last_activity_at | DateTimeField | now | bumped by sync, runs, user moves |
| | | content_hash | CharField(64) | "" | re-triage only when it changes |
| | | raw | JSONField | {} | last source payload |
| agent | AgentRun | card | FK card.Card | CASCADE | related_name="runs" |
| | | kind | CharField(choices) | – | triage, draft, retro |
| | | status | CharField(choices) | queued | queued, running, awaiting_approval, succeeded, failed, cancelled |
| | | current_step | CharField(200) | "" | shown live on the card |
| | | started_at / finished_at | DateTimeField | null | |
| | | skills_used | M2M skill.Skill | – | |
| | | model | CharField(100) | "" | |
| | | input_tokens / output_tokens | PositiveIntegerField | 0 | |
| | | transcript | JSONField | [] | |
| | | error | TextField | "" | |
| agent | ProposedAction | run | FK agent.AgentRun | CASCADE | related_name="actions" |
| | | card | FK card.Card | CASCADE | |
| | | action_type | CharField(choices) | – | odoo_create_ticket, odoo_post_note, gmail_create_draft, gmail_send, create_todo |
| | | payload | JSONField | – | editable before approval |
| | | status | CharField(choices) | proposed | proposed, approved, rejected, executed, failed |
| | | result | JSONField | {} | e.g. created ticket id |
| | | executed_at | DateTimeField | null | |
| skill | SkillRepo | name | CharField(100) | – | "Scrollit Skills", "Personal" |
| | | remote_url | CharField(500) | – | |
| | | local_path | CharField(500) | – | clone location |
| | | default_branch | CharField(100) | main | |
| | | is_shared | BooleanField | True | shared → changes via PR only |
| | | last_pulled_commit | CharField(40) | "" | |
| | | last_pulled_at | DateTimeField | null | |
| skill | Skill | repo | FK skill.SkillRepo | CASCADE | unique with slug |
| | | slug | SlugField | – | |
| | | category | CharField(choices) | other | functional_analysis, technical_analysis, devops, development, support, other (from folder) |
| | | path | CharField(500) | – | relative to repo |
| | | description | TextField | "" | from frontmatter |
| | | content_hash | CharField(64) | – | |
| | | usage_count | PositiveIntegerField | 0 | |
| | | last_used_at | DateTimeField | null | |
| skill | SkillChange | repo | FK skill.SkillRepo | CASCADE | |
| | | skill | FK skill.Skill | null, SET_NULL | null = new skill |
| | | source_run | FK agent.AgentRun | null, SET_NULL | the retro that proposed it |
| | | proposed_content | TextField | – | full new SKILL.md |
| | | diff | TextField | "" | for review |
| | | rationale | TextField | "" | |
| | | status | CharField(choices) | proposed | proposed, approved, rejected, pr_open, merged, committed, failed |
| | | branch / pr_url | CharField / URLField | "" | |

Constraints: `Card` unique (`source`, `external_id`) where source ≠ manual; at most one `AgentRun` per card in (queued, running) — partial unique constraint.

## Business rules
1. Sync upserts cards by (`source`, `external_id`) and never duplicates. A changed source payload bumps `last_activity_at` and `content_hash`. — `connector.services.upsert_card(connection, external_id, data) -> Card`
2. A card whose Odoo record is closed/done moves to `done`. Gmail cards are never auto-closed. — `card.services.apply_source_state(card, data)`
3. A card in `inbox` with a new `content_hash` gets one triage run queued. — `agent.services.queue_run(card, kind) -> AgentRun`
4. Triage sets `client`, `urgency`, `ai_assist_score`, `next_step` and moves the card to `triaged`. With score ≥ 2 it picks a skill and creates ProposedActions, and the card moves to `ai_drafted`. — `agent.services.apply_triage(run, result)`
5. No ProposedAction executes without explicit approval. Execution is idempotent: if `result` holds an external id, re-execution is a no-op. — `agent.services.execute_action(action) -> dict`
6. Activity state is computed, not stored: **running** if a run is queued/running or `timer_running`. **Idle** if not running, column ≠ done and `last_activity_at` < now − `IDLE_AFTER_DAYS`. Otherwise **active**. — `card.services.activity_state(card) -> str` plus `Card.objects.running()`, `.idle()`
7. A run stuck in `running` longer than `AGENT_RUN_TIMEOUT_MIN` (default 15) becomes `failed` and the card is no longer running. — `agent.services.reap_stale_runs()`
8. Misrouted support mail: if triage classifies a Gmail card as a support request and the sender domain matches a `Client`, it proposes (a) `odoo_create_ticket` for the support team with partner, title and description, (b) `odoo_post_note` with issue analysis + proposed solution, (c) `gmail_create_draft` replying that support has the ticket. Action (b) waits for (a)'s ticket id.
9. Moving a card to `done` queues a `retro` run. A retro proposes at most one SkillChange per skill and may propose one new skill. — `skill.services.propose_change(run, skill, content, rationale)`
10. Approving a SkillChange on a shared repo commits to branch `dashboard/<slug>-<yyyymmdd>` and opens a PR; it never pushes to the default branch. On a non-shared repo it commits directly. — `skill.services.apply_change(change)`
11. Repos are pulled on schedule and the skill index is rebuilt from disk. A pull with local uncommitted changes aborts and is reported, never forced. — `skill.services.pull_repo(repo)`, `skill.services.reindex(repo)`
12. Each run records `skills_used` and increments `usage_count` / `last_used_at`.
13. User drag/drop updates `column`, `position` and `last_activity_at`. — `card.services.move_card(card, column, position)`

## Permissions
| Role/Group | Can | Cannot |
|---|---|---|
| Owner (superuser, login required) | everything in the UI and admin | – |
| Claude agent (tool layer) | read Odoo, Gmail, files, skills; create ProposedAction / SkillChange | write to Odoo, Gmail or git |

External rights are inherited from your Odoo API key, Gmail OAuth scopes (`gmail.readonly`, `gmail.compose`) and git credentials. Shared-repo writes go through PR review by colleagues.

## UI
- **Admin**: all models. Card: list_display title, source, client, column, ai_assist_score, last_activity_at; filters source, column, client. AgentRun: card, kind, status, started_at; filter status. SkillChange: repo, skill, status.
- **/board/** (`card/board.html`): columns as defined. A filter bar has client, source and a running / idle / all toggle. The header shows counters ("3 running · 7 idle"). Card face shows source icon, client, title, AI-score dots, next step and an activity badge:
  - running: accent border with subtle pulse, plus `current_step` ("Claude: drafting ticket…") or "Timer running"
  - idle: muted card, "Idle 6d" badge
  - active: normal
- **/card/&lt;id&gt;/** drawer: details, runs timeline, proposed actions with editable payload, Approve / Reject.
- **/skills/**: skills grouped by category with usage, pending SkillChanges with diff, Approve → PR link.
- **/connections/**: sync status, last error, "sync now".
- **HTMX**:
  - drag/drop → `hx-post /card/<id>/move/` → updated column partial
  - running cards only: `hx-get /card/<id>/face/` with `hx-trigger="every 3s"`, returns `card/partials/card_face.html`; polling stops when the partial comes back non-running
  - counters: `hx-get /board/counters/` every 10s
  - Approve: `hx-post /action/<id>/approve/` → drawer actions partial
  - Skill change approve: `hx-post /skills/change/<id>/approve/` → row partial

## Background jobs (Procrastinate)
| Task | Schedule | Idempotency |
|---|---|---|
| `connector.tasks.sync_gmail` | every 5 min | Gmail historyId cursor + upsert |
| `connector.tasks.sync_odoo` | every 5 min | `write_date` cursor + upsert |
| `connector.tasks.scan_files` (phase 3) | every 15 min | path + mtime hash |
| `agent.tasks.run_agent(run_id)` | on queue | skips unless status = queued |
| `agent.tasks.execute_action(action_id)` | on approve | rule 5 |
| `agent.tasks.reap_stale_runs` | every 5 min | status check |
| `skill.tasks.pull_skill_repos` | every 30 min | git fetch + fast-forward only |
| `skill.tasks.apply_skill_change(change_id)` | on approve | skips if branch / PR exists |

## Migrations and data
New apps: `connector`, `card`, `agent`, `skill`. Data migration seeds `Connection` rows (gmail, odoo) and `SkillRepo` "Scrollit Skills" from env. Optional command `import_clients` creates `Client` rows from Odoo partners. New env vars in `.env.example`: `ODOO_URL`, `ODOO_DB`, `ODOO_API_KEY`, `GMAIL_CLIENT_SECRET_FILE`, `ANTHROPIC_API_KEY`, `SKILLS_REPO_URL`, `SKILLS_REPO_PATH`, `FILES_ROOT`, `IDLE_AFTER_DAYS`, `AGENT_RUN_TIMEOUT_MIN`.

## Tests
- R1 upsert twice → one card; changed payload bumps `last_activity_at`
- R2 closed Odoo ticket → done; archived Gmail thread stays
- R3 unchanged hash → no second triage run
- R4 score 3 → `ai_drafted` + actions; score 0 → `triaged`, no actions
- R5 unapproved action not executed; executed twice → one external call (mock)
- R6 running via run, running via timer, idle after threshold, done never idle
- R7 stale run reaped
- R8 support mail with known domain → ticket, note and draft actions in order
- R9 move to done → retro queued
- R10 shared repo → branch + PR (mock git host); personal repo → direct commit
- R11 dirty working tree → pull aborted, error recorded
- R12 skills_used increments usage
- R13 move updates column/position
- Smoke: /board/, /card/&lt;id&gt;/, /skills/, /connections/, all HTMX endpoints

## Investigate first
- Scrollit Odoo: version, that `/json/2` is reachable with an API key, Helpdesk installed, support team id, which fields expose a running timer on tasks/tickets, and what your user may create.
- Google Workspace: whether the Scrollit admin allows a self-made OAuth desktop client with Gmail scopes.
- Claude Agent SDK: Python package, how to point it at skill folders from the local repo clone, and how to expose read-only custom tools plus a `propose_action` tool.
- Scrollit Skills repo: host, folder structure vs. the category choices above, branch protection, and how to open PRs from a script.
- Template: Procrastinate periodic tasks already wired; whether SortableJS (static file) is acceptable for drag/drop.

## Open questions
1. Confirm "running" includes an Odoo timer, not only Claude runs.
2. Is HTMX polling enough for live state, or do we want SSE later?
3. Skills repo host (GitHub/GitLab) and who reviews PRs.
4. Keep a separate personal skills repo next to the shared one?
5. Data terms for sending client mails/tickets to Claude via the Scrollit org account.

---

## v1 implementation notes (phase 1 built, October 2026)

Built: phase 1 plus read-only skills indexing. Not built yet: retro on Done, `SkillChange`, PRs to the skills repo (phase 2), files/Drive (phase 3).

Deviations from the analysis above, and why:

| Area | Analysis said | v1 does | Why |
|---|---|---|---|
| Claude runtime | Claude Agent SDK | Anthropic Messages API with a small tool-use loop (`agent/claude.py`) | No Node/CLI dependency; tools stay read-only by construction. Skills are loaded on demand with a `read_skill` tool (progressive disclosure, like Agent Skills). |
| Executing actions | `execute_action` Procrastinate task | Runs synchronously in the approve request | Immediate success/error in the drawer; every action is a single quick API call. |
| Gmail sync | `historyId` cursor | Query poll (`GMAIL_QUERY`) + content hash | Simpler, idempotent; good enough for one inbox. |
| Gmail actions | draft or send | Draft only (`gmail.compose`) | You always press Send yourself in v1. |
| Odoo sync | `write_date` cursor | Full fetch of *my open* tasks/tickets/activities every 5 min | Small sets; lets us notice closed/reassigned records (they move to Done). Missing apps (no Helpdesk) are skipped, never closed. |
| Skill.category | fixed choices | Free text: frontmatter `category`/`metadata.category`, else plugin name (`plugins/<plugin>/skills/...`), else parent folder | Matches scrollit/claude-skills (marketplace layout) and plain folders. |
| Skills branch | `main` | Empty = remote default branch | scrollit/claude-skills uses `master`. |
| Extra fields | – | `Card.summary`, `AgentRun.result`, `ProposedAction.sequence/title/depends_on/error`, `SkillRepo.last_error` | Ordering and dependencies between actions (note needs the ticket id). |

### Still to verify against the real Scrollit Odoo
- `message_post` with a plain-text `body` over JSON-2: check whether newlines survive in the chatter; switch to HTML if needed.
- Record URLs `/odoo/<model>/<id>` open correctly on your version.
- `timer.timer` fields (`timer_start`, `res_model`, `res_id`, `user_id`) and `project.task.state` values (`1_done`, `1_canceled`).
- The `helpdesk.team` id for `ODOO_SUPPORT_TEAM_ID`, and what your API key's user may create.
