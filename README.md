# Bott

**Bott** is a conversational engineering teammate in Slack — an [Agno](https://github.com/agno-agi/agno)
`Team` manager with a personality, backed by a team of specialist agents it delegates to.
Talk to it like a colleague; it chats directly and hands real work to the right specialist.
The first specialist is **Code Review**: it fetches a PR, shallow-clones the repo, lets an
agent investigate with file/search/history tools, runs a 10-precondition **verdict gate**,
and renders a GitHub review and/or a Slack message.

Three ways in (the manager is the *conversational* door; webhooks and cron hit specialists directly):

- **Slack** — talk to Bott; it delegates PR reviews and (later) other tasks. Thread replies drive evidence-bound re-reviews.
- **GitHub webhook** — auto-review on PR opened / ready-for-review (direct trigger).
- **CLI** — dry-run a code review and print the verdict, gate table, and rendered output.

## Layout

```
src/bott/
├── manager/               # the conversational manager (Agno Team leader)
│   ├── manager.py         #   builds the Team, wires members + routing
│   └── personality.py     #   Bott's voice — single source of truth
├── agents/                # specialist agents the manager delegates to
│   └── code_review/       #   first specialist (the PR reviewer)
│       ├── member.py      #     Team-member adapter + enqueue tools
│       ├── pr_ref.py      #     PR-reference parsing
│       ├── cli.py         #     `pr-review` dry-run (direct trigger)
│       ├── webhook.py     #     GitHub PR webhook (direct trigger)
│       ├── core/          #     pipeline, runner, verdict_gate, rereview, models, types
│       ├── github/        #     client, app_auth (JWT), clone, fetch_essentials
│       ├── agent/         #     prompt, tools (Agno Toolkit), diff_hunks, noise
│       └── rendering/     #     github.py, slack.py
├── shared/                # used by the manager and every specialist
│   ├── config.py          #   env, model, budget caps, gate thresholds, DB path
│   ├── persistence/       #   store.py (SQLite task queue + review traces)
│   └── observability/     #   logging_setup.py (secret-redacting logs)
└── interfaces/            # slack_app.py (front door) + server.py (boots it all)
tests/                     # pytest suite (deterministic unit tests)
```

Future specialists (standup, delivery synthesis, engagement hygiene, incident triage)
drop into `bott/agents/` as new members — no change to the manager's routing layer.
The Next.js chat frontend lives separately in `agent-ui/`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # installs the package + dev tools (pytest, ruff)
cp .env.example .env           # then fill in OPENAI_API_KEY, Slack tokens, etc.
```

## Run

```bash
# CLI dry-run (posts nothing unless --post and the repo is in ALLOWED_POST_REPOS):
pr-review owner/repo/123
pr-review https://github.com/owner/repo/pull/123 --model gpt-4o-mini

# Bott server (Slack Socket Mode + GitHub webhook + shared worker):
pr-review-server               # equivalently: python -m bott.interfaces.server
```

### Live webhook (local dev)

GitHub webhooks need a public URL. `scripts/run_server.sh` stops any stale server,
starts `pr-review-server`, opens a `cloudflared` tunnel, and prints the public webhook
URL. GitHub Apps have one webhook URL and the tunnel changes each run, so
`scripts/set_app_webhook.py` repoints the App at the current URL (authenticating as the
App; it reuses `GITHUB_WEBHOOK_SECRET` so signatures still verify).

```bash
scripts/run_server.sh                        # server + tunnel, waits for health, registers webhook
scripts/run_server.sh --no-webhook           # same, but skip registering (print the URL instead)
python scripts/set_app_webhook.py https://<tunnel>.trycloudflare.com/webhook/github
```

For a setup you don't have to re-point each run, use a **named** cloudflared tunnel with a
stable hostname routed to `http://localhost:$WEBHOOK_PORT` and register the App webhook to
that hostname once.

A `pull_request` opened/ready_for_review event then auto-reviews the PR, posts the review
(if the repo is in `ALLOWED_POST_REPOS`), and mirrors it to `REVIEW_SLACK_CHANNEL`. If a
delivery failed while nothing was listening, redeliver it from the App's **Advanced →
Recent Deliveries** page (or the `/app/hook/deliveries` API).

## Configuration

All settings come from the environment (see `.env.example`). Key vars: `OPENAI_API_KEY`,
`REVIEW_MODEL`, `REVIEW_MAX_*` budget caps, the `REVIEW_*` gate thresholds,
`GITHUB_*` (App auth + webhook), `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`,
`ALLOWED_POST_REPOS`, and `REVIEW_DB_PATH`.

## Test & lint

```bash
pytest
ruff check src tests
```
