#!/usr/bin/env bash
# Run a SECOND Bott instance, dedicated to workspace B, alongside the primary one.
#
# Shared/workspace-agnostic secrets (Jira, Spin, Memra, model, GitHub) come from .env;
# .env.workspace-b overrides the workspace-B specifics (Slack creds + distinct ports/DBs)
# so the two instances never collide. .env.workspace-b is sourced LAST so it wins.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env.workspace-b ]; then
  echo "Missing .env.workspace-b — fill in workspace B's Slack creds first." >&2
  exit 1
fi

set -a
[ -f .env ] && . ./.env
. ./.env.workspace-b
set +a

echo "Starting Bott for workspace B on port ${BOTT_PORT} (db=${AGENTOS_DB_PATH}, proxy=:${CODEX_PROXY_PORT})"
exec bott-app
