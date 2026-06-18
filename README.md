# Bott

**Bott** is a conversational engineering teammate that lives in Slack. It's a single
[Agno](https://github.com/agno-agi/agno) **agent** with a personality and a set of
specialized **skills** (tools) — not a team of agents. You talk to it like a colleague in
a DM or by `@mention`; it answers from real context, reviews pull requests, and runs
scheduled flows on a cadence. It runs as one [AgentOS](https://github.com/agno-agi/agno)
app (FastAPI), and every interaction is scoped per user (`user_id`) and conversation
(`session_id`) so no one's data bleeds into anyone else's.

This is a **Slack-only POC** to validate Agno as the platform. One agent, several skills,
isolation at the session/user level — no router, no team, no separate apps.

## What it does

Five use cases, all served by the one agent:

- **PR Reviews** — `@mention` a GitHub PR (or follow up in-thread for a re-review), or let
  the GitHub webhook auto-review on PR open / ready-for-review. The agent enqueues the
  work; a durable worker fetches the PR, shallow-clones the repo, investigates with
  file/search/history tools, runs a 10-precondition **verdict gate**, and posts a rendered
  review to GitHub (when the repo is allow-listed) and mirrors it to Slack.
- **DSM (daily standup)** — form-driven and threaded: at the open time a channel message
  with an **"Add my update"** button collects async updates; a **pre-read** summary posts
  in the thread before the call; after the call a **summary** (from Memra meeting notes)
  posts in the same thread. Scoped per team.
- **Delivery Synthesis** — a scheduled per-engagement digest (status, top risks, what's
  going well, next steps) grounded in Memra context and posted to the engagement's channel.
- **Personal Concierge** — per-user action items from per-user memory; each user only ever
  sees their own items.
- **Security Advisories** — a scheduled Drupal security-advisory digest (severity-grouped,
  CVEs, fix versions), also answerable on demand in chat.

Schedules are managed from a **Slack App Home** control panel (add / run-now / remove).
**Context comes from [Memra](https://memra.team)** — a read-only layer over MCP
(engagements, people, delivery, risks, meeting notes); the agent prefers cited context
over guessing.

## Architecture

```
Slack (Events API)  ─┐
GitHub webhook      ─┼─►  AgentOS app (FastAPI)  ──►  Bott agent (one agent, many skills)
Scheduler (cron)    ─┘         │                          │
                               │                          ├─ Memra tools (read-only context)
                               │                          ├─ PR-review tools (enqueue)
                               │                          ├─ Slack tools (post)
                               │                          └─ agentic memory (per user_id)
                               │
                               └─►  durable worker  ──►  review pipeline → verdict gate
                                     (SQLite queue)        → GitHub review + Slack mirror
```

- **One agent, not a team.** `agents/bott_agent.py` builds a single `Agent` with the
  skill tools attached. Isolation lives at `user_id`/`session_id`, which the Slack
  interface supplies on every run (`resolve_user_identity=True` → `user_id` = the user's
  email). Per-user memory uses Agno **agentic memory** (the agent stores/recalls only when
  it decides to, so trivial chit-chat shows no "thinking" trace).
- **Slack over the Events API** (HTTP, not Socket Mode). Chat runs on Agno's built-in
  `agno.os.interfaces.slack.Slack` (mounted at `/slack/chat`); a thin gateway at
  `/slack/events` handles `app_home_opened` and forwards chat events to it. The interface
  passes `channel_id`/`thread_ts` into each run as dependencies so the review tools know
  where to post. The **App Home** control panel (`interfaces/slack_home/`) handles the
  schedule buttons + modals at `/slack/interactivity`.
- **Reviews run out-of-band.** The review tools only *enqueue*; the durable worker
  (`interfaces/slack_app.py`) runs the pipeline, posts live progress + the verdict, and
  persists the trace. Reviews are slow (clone + LLM), so they never block a chat turn.
- **Scheduler.** `scheduler=True` on AgentOS; `skills/scheduling.py` registers delivery /
  DSM / concierge / security schedules (created from the App Home panel) that fire the
  agent's run endpoint. Each schedule embeds `user_id`/`session_id` in its payload, so
  scheduled runs stay scoped just like live ones.
- **Pluggable model backend** (`shared/codex.py`). For the single-user POC, models run on
  the owner's ChatGPT/Codex subscription with **no API key** via a local OpenAI-compatible
  proxy that the app auto-starts and self-heals. For multi-user production, flip
  `MODEL_BACKEND=openai` and use a sanctioned key. See *Model backend* below.

### Layout

```
src/bott/
├── agents/
│   ├── bott_agent.py       # THE agent — one agent + skill tools (assembled here)
│   ├── personality.py      # Bott's voice/identity (single source of truth)
│   └── code_review/        # PR-review skill
│       ├── member.py       #   enqueue tools (start_review / start_rereview)
│       ├── webhook.py      #   GitHub PR webhook → enqueue
│       ├── pr_ref.py       #   PR-reference parsing
│       ├── cli.py          #   `pr-review` dry-run
│       ├── core/           #   pipeline, runner, verdict_gate, rereview, models, types
│       ├── github/         #   client, app_auth (App JWT → installation token), clone, fetch
│       ├── agent/          #   prompt, tools (Agno Toolkit), diff_hunks, noise
│       └── rendering/      #   github.py, slack.py (verdict rendering)
├── skills/
│   ├── scheduling.py       # schedule helpers: delivery synthesis, DSM, concierge, security
│   ├── advisories.py       # Drupal security-advisory digest (fetch + render + post)
│   └── dsm.py              # standup: open collection / pre-read / post-call summary
├── shared/
│   ├── config.py           # env, model selection, budget caps, gate thresholds, DB paths
│   ├── codex.py            # Codex-subscription proxy: auto-start + supervise (or openai backend)
│   ├── model.py            # single place the model is built
│   ├── context/memra.py    # Memra client + read-only MCP tools (cited)
│   ├── persistence/        # store.py (review queue + traces), standup.py (DSM rounds)
│   └── observability/      # logging_setup.py (secret-redacting logs)
└── interfaces/
    ├── app.py              # the AgentOS app: agent + Slack + scheduler + webhook (`bott-app`)
    ├── slack_app.py        # durable PR-review worker + Slack posting (imported by app.py)
    └── slack_home/         # Slack App Home control panel: schedules + buttons + modals
tests/                      # pytest suite (deterministic unit tests)
scripts/
├── isolation_test.py       # two-user isolation gate (the make-or-break check)
├── setup_schedules.py      # register the delivery/DSM/concierge schedules
├── eval_reviews.py         # score review verdicts against a manifest (live, spends tokens)
└── set_app_webhook.py      # point the GitHub App's webhook at the current public URL
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # or: uv sync   (uv.lock pins exact versions)
cp .env.example .env           # then fill in the vars below
```

Requires **agno ≥ 2.2.2** (the isolation fix for CVE-2025-64168); the lockfile pins a
current version.

## Run

```bash
bott-app                       # the whole POC: agent + Slack + scheduler + webhook worker
                               # (equivalently: python -m bott.interfaces.app)

pr-review owner/repo/123       # CLI dry-run of a single review (posts nothing by default)
```

On startup `bott-app` brings up the model backend (the Codex proxy, in the default
`codex` backend), starts the PR-review worker, mounts the Slack interface (if Slack creds
are present) and the GitHub webhook router, and serves on `BOTT_PORT` (default `7777`).

### Public URL (Slack events + GitHub webhook)

Both Slack's Events API and the GitHub webhook need to reach the app over HTTPS. Use a
**named** `cloudflared` tunnel with a stable hostname routed to `http://localhost:7777`,
and register:

- the Slack app's **Event Subscriptions** request URL → `https://<host>/slack/events`
  (this gateway handles `app_home_opened` and forwards chat events to Agno's interface at
  `/slack/chat/events`; subscribe to `message.im`, `app_mention`, and `app_home_opened`)
- the Slack app's **Interactivity** request URL → `https://<host>/slack/interactivity`
  (the App Home buttons + modals), and turn on the **App Home** tab
- the GitHub App's webhook → `https://<host>/webhook/github`
  (`python scripts/set_app_webhook.py https://<host>/webhook/github` repoints it; it reuses
  `GITHUB_WEBHOOK_SECRET` so signatures still verify).

A `pull_request` opened/ready_for_review event then auto-reviews the PR, posts the review
(if the repo is in `ALLOWED_POST_REPOS`), and mirrors it to `REVIEW_SLACK_CHANNEL`.

### Scheduled flows

```bash
python scripts/setup_schedules.py      # edit the engagement/team/user rows first
```

Schedules persist in the DB; the running app's scheduler fires them. To test one without
waiting for cron, trigger it on demand — `ScheduleManager(db).trigger(<id>)` or
`POST /schedules/<id>/trigger`.

## Configuration

All settings come from the environment (see `.env.example`). Key vars:

- **Slack:** `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` (Events API). `resolve_user_identity`
  maps Slack users to emails for `user_id`.
- **GitHub App + webhook:** `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` / `_PATH`,
  `GITHUB_WEBHOOK_SECRET`, `ALLOWED_POST_REPOS` (repos the bot may post to),
  `REVIEW_SLACK_CHANNEL` (where webhook reviews mirror).
- **Memra:** `MEMRA_CLIENT_ID`, `MEMRA_CLIENT_SECRET`, `MEMRA_TOKEN_ENDPOINT`,
  `MEMRA_MCP_ENDPOINT`, `MEMRA_SCOPE`.
- **Models:** `MODEL_BACKEND` (`codex` | `openai`), `REVIEW_MODEL` / `MANAGER_MODEL`,
  `REVIEW_MODEL_BASE_URL` / `MANAGER_MODEL_BASE_URL`, `OPENAI_API_KEY` (openai backend),
  `REVIEW_MAX_*` budget caps, the `REVIEW_*` gate thresholds.
- **DBs:** `REVIEW_DB_PATH` (worker queue + traces), `AGENTOS_DB_PATH` (sessions/memory).
  SQLite by default; a Postgres `docker-compose.yml` is included as an option.

## Model backend

The model is built in one place (`shared/model.py`), so the app isn't tied to OpenAI + an
API key.

- **Codex subscription (default, POC, no API key):** `MODEL_BACKEND=codex`. The app
  auto-starts a local proxy (`npx openai-oauth`, port `10531`) that reuses your
  `~/.codex/auth.json` and exposes an OpenAI-compatible endpoint, then points the agent at
  it and supervises it (respawns on crash/hang). Run `npx @openai/codex login` once first.
  **Single-user only** — it reuses one ChatGPT login and rides Codex's undocumented
  backend (ToS-gray, account-flagging risk). Fine for a personal POC; not for production.
- **Sanctioned OpenAI key (multi-user production):** `MODEL_BACKEND=openai` + a real
  `OPENAI_API_KEY`. No proxy.
- **Any OpenAI-compatible endpoint** (Azure / OpenRouter / self-hosted / Ollama): set
  `REVIEW_MODEL_BASE_URL` (+ `REVIEW_MODEL_API_KEY` if it needs one).

## Test & validate

```bash
pytest                              # deterministic unit suite (no tokens spent)
ruff check src tests scripts

python scripts/isolation_test.py    # two-user isolation gate — plants a secret as user A,
                                    # proves user B can't read it (memory/session/history).
                                    # LIVE (spends tokens). Make-or-break for concierge.

python scripts/eval_reviews.py      # score review verdicts vs scripts/eval_cases.json.
                                    # LIVE (clones + reviews PRs) — run on demand, not in CI.
```
