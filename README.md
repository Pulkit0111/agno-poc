# Bott

**Bott** is a conversational engineering teammate that lives in Slack. It's a single
[Agno](https://github.com/agno-agi/agno) **agent** with a personality and a set of
specialized **skills** (tools) — not a team of agents. You talk to it like a colleague in
a DM or by `@mention`; it answers from real context, reads your connected systems,
reviews and fixes code, and runs scheduled flows on a cadence. It runs as one
[AgentOS](https://github.com/agno-agi/agno) app (FastAPI) backed entirely by **Postgres**,
and every interaction is scoped per user (`user_id`) and conversation (`session_id`) so no
one's data bleeds into anyone else's.

One agent, many skills, isolation at the session/user level — no router, no team, no
separate apps. Slack is the only frontend; everything is reachable by natural language.

## What it does

All served by the one agent:

- **Connectors (read-only)** — one modular registry of outside systems. *Org-credential:*
  Jira, Confluence, Slack, [Memra](https://memra.team) (org context), and **Sentry**.
  *Domain-delegated (per-user):* **Gmail, Drive, Calendar** — the agent reads *your own*
  mail/files/calendar via a Google Workspace service account that impersonates the verified
  Slack caller (read-only; "only my data" is enforced structurally).
- **Build & Fix** — describe a change, point at a GitHub issue or a Jira ticket, and Bott
  drafts a plan, posts it for **approval**, then (on approve) clones the repo, implements
  until tests pass, and opens a **draft PR**. Write access is gated by a repo allowlist.
- **PR review** — `@mention` a PR (or let the GitHub webhook auto-review on open); a durable
  worker clones, investigates, runs a verdict gate, posts to GitHub (allow-listed repos) and
  mirrors to Slack.
- **Sentry triage** — `triage this Sentry issue in owner/repo`: Bott reads the incident +
  recent events, diagnoses the root cause, proposes a fix, and on approval flows it straight
  into Build & Fix (→ draft PR).
- **Self-authored skills + curator** — teach Bott a new reusable workflow in plain language
  (`author_skill`); it's saved durably in Postgres, loads immediately, and survives restarts.
  Admins curate the library (`list_skills` / `pin` / `retire`).
- **Delivery & reporting** — DSM (daily standup), per-engagement delivery synthesis, personal
  concierge, Drupal security-advisory digest, sprint reports, and a portfolio risk roll-up —
  grounded in Memra context, posted to Slack (some published to a hosted URL via Spin).

Schedules and admin actions are managed from a **Slack App Home** control panel; approvals
use **Approve / Dismiss** buttons in-thread.

## Architecture

```
Slack (Events API)  ─┐
GitHub webhook      ─┼─►  AgentOS app (FastAPI)  ──►  Bott agent (one agent, many skills)
Scheduler (cron)    ─┘         │                          │
                               │                          ├─ Connectors (registry): read-only
                               │                          │    org-cred + domain-delegated
                               │                          ├─ Build & Fix / triage (enqueue)
                               │                          ├─ Skills (author/curate) + memory
                               │                          └─ Slack posting
                               │
                               └─►  durable worker(s)  ──►  plan / implement / review / triage
                                     (Postgres queue,        → approval gate → GitHub PR
                                      FOR UPDATE SKIP LOCKED)  → Slack mirror
```

- **One agent, not a team.** `agents/bott_agent.py` builds a single `Agent` from the skill
  tools. Isolation lives at `user_id`/`session_id`, supplied by the Slack interface on every
  run (`resolve_user_identity=True` → `user_id` = the user's email). Per-user agentic memory.
- **Postgres is the only datastore.** Jobs, approvals, encrypted connector tokens, settings,
  authored skills, sessions/memory, and review traces all live in Postgres. The job queue
  uses `FOR UPDATE SKIP LOCKED` (split-ready worker). Secrets are encrypted at rest
  (Fernet / `BOTT_SECRET_KEY`); logs are secret-redacting.
- **Pluggable model gateway** (`shared/model.py`, `build_model(role)`). Three providers:
  **codex** (an **org-level** ChatGPT/Codex subscription — one shared OAuth token, centrally
  refreshed, no per-user keys; direct OpenAI-compatible adapter that re-resolves the token so
  a long-lived agent never holds a stale one), **bedrock**, and **openrouter**. A settings
  override (Postgres) beats env. Admins connect/switch models from App Home.
- **Connector registry** (`skills/connectors/`). Every connector declares an **auth pattern**
  (org-credential / domain-delegated / per-user-OAuth) and registers through `register_all.py`;
  `build_agent` wires them via `REGISTRY.all_tools()`. For delegated connectors, *whose*
  account is read is bound to the verified `run_context.user_id` — never a tool argument.
- **Approval gate.** World-changing actions (open a PR, implement a fix) are never taken
  directly: a plan/diagnosis is posted with Approve/Dismiss; only an approved, **allow-listed**
  row is turned into an `implement` job (the single implement path).
- **Slack over the Events API** (HTTP, not Socket Mode). Chat runs on Agno's built-in Slack
  interface (mounted at `/slack/chat`); a thin gateway at `/slack/events` handles
  `app_home_opened` and forwards chat events. App Home buttons/modals + approvals post to
  `/slack/interactivity`.

### Layout

```
src/bott/
├── agents/
│   ├── bott_agent.py       # THE agent — one agent + skill tools (assembled here)
│   ├── personality.py      # Bott's voice/identity
│   ├── build_fix/          # plan → approve → implement → draft PR
│   ├── code_review/        # PR review (enqueue + durable pipeline + verdict gate)
│   └── triage/             # Sentry triage → diagnose → approve → Build & Fix
├── skills/
│   ├── connectors/         # registry + jira/confluence/slack/memra/sentry (org),
│   │                       #   gmail/drive/calendar (domain-delegated, read-only)
│   ├── skill_authoring.py  # author_skill + curator (list/pin/retire, admin-gated)
│   ├── scheduling.py       # delivery / DSM / concierge / security schedules
│   ├── advisories.py, dsm.py, engagement_data.py, sprint_report/, portfolio/, web_publish.py
│   ├── workspace_tools.py  # coding/python/session-search + skill_manage
│   └── library/            # curated SKILL.md library (+ authored skills materialized here)
├── shared/
│   ├── config.py           # env, model selection, gates, thresholds
│   ├── model.py            # build_model(role) — the 3-provider gateway
│   ├── codex_tokens.py, codex_model.py   # org Codex token manager + re-resolving adapter
│   ├── schema.py           # SQLAlchemy Core: the single source of truth for tables
│   ├── approvals.py, identity.py, secrets.py
│   ├── persistence/        # queue.py, records.py, skills_store.py, standup.py
│   ├── integrations/       # jira.py, sentry.py, spin.py (REST clients)
│   ├── context/memra.py    # Memra client + read-only MCP tools (cited)
│   └── observability/      # secret-redacting logging
└── interfaces/
    ├── app.py              # the AgentOS app: agent + Slack + scheduler + worker (`bott-app`)
    ├── slack_app.py        # durable worker: plan / implement / review / triage
    └── slack_home/         # Slack App Home control panel + approvals + webhook
tests/                      # pytest suite (deterministic unit tests)
```

## Setup

```bash
uv sync                        # installs deps into .venv  (or: python -m venv .venv && pip install -e ".[dev]")
cp .env.example .env           # then fill in the vars below
createdb bott                  # Postgres; set DATABASE_URL to point at it
```

Requires **agno ≥ 2.2.2** (the isolation fix for CVE-2025-64168); the lockfile pins a current
version. Tables are created automatically on first run.

## Run

```bash
uv run bott-app                # the whole app: agent + Slack + scheduler + worker
                               # (equivalently: python -m bott.interfaces.app)

pr-review owner/repo/123       # CLI dry-run of a single review (posts nothing)
```

On startup `bott-app` initializes the schema, seeds the org Codex token (from
`~/.codex/auth.json` if present), materializes authored skills to the library, starts the
durable worker, mounts the Slack interface (if creds are present) and the GitHub webhook, and
serves on `BOTT_PORT` (default `7777`).

### Public URL (Slack events + GitHub webhook)

Slack's Events API and the GitHub webhook reach the app over HTTPS. Point a tunnel/host at
`http://localhost:7777` and register:

- Slack **Event Subscriptions** → `https://<host>/slack/events` (subscribe to `message.im`,
  `app_mention`, `app_home_opened`); enable the **App Home** tab.
- Slack **Interactivity** → `https://<host>/slack/interactivity`.
- GitHub App webhook → `https://<host>/webhook/github`.

## Configuration

All settings come from the environment (see `.env.example`). Key groups:

- **Core:** `DATABASE_URL` (Postgres), `BOTT_SECRET_KEY` (Fernet), `BOTT_ADMINS`
  (comma-separated admin emails), `ALLOWED_EMAIL_DOMAIN` (default `axelerant.com`).
- **Model:** `MODEL_PROVIDER` (`codex` | `bedrock` | `openrouter`, default `codex`),
  `BOTT_CHAT_MODEL` / `BOTT_HEAVY_MODEL`, `OPENROUTER_API_KEY` / AWS creds as applicable. The
  org Codex token is connected once (host `~/.codex/auth.json` or App Home → Connect Codex).
- **Slack:** `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`.
- **GitHub App (build/review/triage PRs):** `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` /
  `_PATH`, `GITHUB_WEBHOOK_SECRET`, `ALLOWED_POST_REPOS` (allowlist), `REVIEW_SLACK_CHANNEL`.
- **Connectors:** Jira (`JIRA_BASE_URL`/`JIRA_EMAIL`/`JIRA_API_TOKEN`), Confluence (falls back
  to Jira), Sentry (`SENTRY_ORG_SLUG`/`SENTRY_API_TOKEN`), Google delegation
  (`GOOGLE_SERVICE_ACCOUNT_PATH` + domain-wide delegation for the `gmail/drive/calendar
  .readonly` scopes), Memra (`MEMRA_*`), Spin (`SPIN_*`). Each is independent — leave any
  unset and that connector simply stays off.

## Test & validate

```bash
pytest                              # deterministic unit suite (no tokens spent)
ruff check src tests scripts

python scripts/isolation_test.py    # two-user isolation gate (LIVE — spends tokens):
                                    # plants a secret as user A, proves user B can't read it.
python scripts/eval_reviews.py      # score review verdicts vs a manifest (LIVE, on demand).
python scripts/eval_codex.py        # verify the org Codex backend end-to-end (LIVE, on demand).
```
