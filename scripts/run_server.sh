#!/usr/bin/env bash
# Dev runner for the Bott server + a public webhook tunnel.
#
# 1. Stops any stale process on the webhook port (e.g. a pre-refactor server).
# 2. Starts the refactored server (bott.interfaces.server): Slack + GitHub webhook + worker.
# 3. Starts a cloudflared tunnel and prints the public webhook URL.
# 4. With --set-webhook, also registers that URL on the GitHub App.
#
# Usage:  scripts/run_server.sh [--set-webhook]
# Ctrl-C stops the server and the tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${WEBHOOK_PORT:-8085}"
PY="${PYTHON:-.venv/bin/python}"
SET_WEBHOOK="${1:-}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Stopping process already on :$PORT ..."
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi

echo "Starting bott server -> /tmp/bott-server.log"
"$PY" -m bott.interfaces.server >/tmp/bott-server.log 2>&1 &
SERVER_PID=$!

echo "Starting cloudflared tunnel -> /tmp/bott-tunnel.log"
cloudflared tunnel --url "http://localhost:$PORT" >/tmp/bott-tunnel.log 2>&1 &
TUNNEL_PID=$!
trap 'kill "$SERVER_PID" "$TUNNEL_PID" 2>/dev/null || true' INT TERM

URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/bott-tunnel.log | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done

echo
echo "server pid=$SERVER_PID  tunnel pid=$TUNNEL_PID"
if [ -n "$URL" ]; then
  HOOK="$URL/webhook/github"
  echo "Public webhook URL: $HOOK"
  if [ "$SET_WEBHOOK" = "--set-webhook" ]; then
    "$PY" scripts/set_app_webhook.py "$HOOK"
  else
    echo "Register it on the GitHub App:  $PY scripts/set_app_webhook.py $HOOK"
  fi
else
  echo "Could not detect tunnel URL — see /tmp/bott-tunnel.log"
fi
echo "Logs: /tmp/bott-server.log  /tmp/bott-tunnel.log"
echo "Ctrl-C to stop."
wait
