#!/usr/bin/env bash
# Dev runner for the Bott server + a public webhook tunnel.
#
# 1. Stops any stale process on the webhook port (e.g. a pre-refactor server).
# 2. Starts the refactored server (bott.interfaces.server): Slack + GitHub webhook + worker,
#    and waits until /healthz is green.
# 3. Starts a cloudflared tunnel, waits for the public URL, and verifies it reaches the server.
# 4. Registers that URL on the GitHub App (skip with --no-webhook).
#
# Usage:  scripts/run_server.sh [--no-webhook]
# Ctrl-C stops the server and the tunnel.
#
# Durable alternative: instead of an ephemeral quick tunnel, run a *named* cloudflared
# tunnel with a stable hostname routed to http://localhost:$WEBHOOK_PORT and set the App
# webhook to that hostname once — then you never re-point it.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${WEBHOOK_PORT:-8085}"
PY="${PYTHON:-.venv/bin/python}"
NO_WEBHOOK="${1:-}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Stopping process already on :$PORT ..."
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi

echo "Starting bott server -> /tmp/bott-server.log"
"$PY" -m bott.interfaces.server >/tmp/bott-server.log 2>&1 &
SERVER_PID=$!
cloudflared_pid=""
trap 'kill "$SERVER_PID" ${cloudflared_pid:-} 2>/dev/null || true' INT TERM

# Wait for the server to be healthy before exposing it.
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://localhost:$PORT/healthz" 2>/dev/null; then break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Server exited during startup — see /tmp/bott-server.log"; tail -20 /tmp/bott-server.log; exit 1
  fi
  sleep 1
done
echo "Server healthy on :$PORT (pid=$SERVER_PID)"

echo "Starting cloudflared tunnel -> /tmp/bott-tunnel.log"
cloudflared tunnel --url "http://localhost:$PORT" >/tmp/bott-tunnel.log 2>&1 &
cloudflared_pid=$!

URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/bott-tunnel.log | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done

if [ -z "$URL" ]; then
  echo "Could not detect tunnel URL — see /tmp/bott-tunnel.log"; exit 1
fi

# Verify the public URL actually routes to our server.
code="$(curl -s -o /dev/null -w '%{http_code}' "$URL/healthz" || true)"
echo "Tunnel: $URL  (public /healthz -> $code)"
[ "$code" = "200" ] || echo "WARNING: tunnel did not return 200 yet; it may need a few more seconds."

HOOK="$URL/webhook/github"
if [ "$NO_WEBHOOK" = "--no-webhook" ]; then
  echo "Register it on the GitHub App:  $PY scripts/set_app_webhook.py $HOOK"
else
  "$PY" scripts/set_app_webhook.py "$HOOK"
fi

echo "Logs: /tmp/bott-server.log  /tmp/bott-tunnel.log"
echo "Ctrl-C to stop."
wait
