# pr_reviewer

An [Agno](https://github.com/agno-agi/agno)-powered pull-request reviewer. It fetches a
PR, shallow-clones the repo, lets an agent investigate with file/search/history tools,
runs a 10-precondition **verdict gate** over the model's output, and renders a GitHub
review and/or a Slack message. Drive it three ways:

- **CLI** — dry-run a review and print the verdict, gate table, and rendered output.
- **Slack bot** — `@bot review <PR-URL>`; thread replies drive evidence-bound re-reviews.
- **GitHub webhook** — auto-review on PR opened / ready-for-review.

## Layout

```
src/pr_reviewer/
├── config.py            # env, model, budget caps, gate thresholds, DB path
├── intake.py            # conversational intent classifier (Slack)
├── core/                # pipeline, runner, verdict_gate, rereview, models, types
├── github/              # client, app_auth (JWT), clone, fetch_essentials
├── agent/               # prompt, tools (Agno Toolkit), diff_hunks, noise
├── rendering/           # github.py, slack.py
├── persistence/         # store.py (SQLite task queue + review traces)
├── observability/       # logging_setup.py (secret-redacting logs)
└── interfaces/          # cli.py, server.py, slack_app.py, webhook.py
tests/                   # pytest suite (pure unit tests)
```

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

# Production server (Slack Socket Mode + GitHub webhook + shared worker):
pr-review-server               # equivalently: python -m pr_reviewer.interfaces.server
```

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
