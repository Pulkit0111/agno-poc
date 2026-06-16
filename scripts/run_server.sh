#!/usr/bin/env bash
# Dev runner for the Bott server + a public webhook tunnel (+ optional Codex proxy).
#
#   scripts/run_server.sh [--codex] [--no-webhook]
#
# --codex      Also start a local Codex-subscription proxy (default: `npx openai-oauth`),
#              which reuses your ChatGPT login in ~/.codex/auth.json and exposes an
#              OpenAI-compatible endpoint. Bott is then pointed at it (no API key).
#              Override the proxy command with CODEX_PROXY_CMD / its port with CODEX_PROXY_PORT.
# --no-webhook Don't register the tunnel URL on the GitHub App (just print it).
#
# Steps: (optional Codex proxy) -> stop stale server -> start server -> tunnel ->
# verify reachable -> register webhook. Ctrl-C stops everything.
#
# NOTE: the Codex proxy is third-party code that reads password-equivalent tokens from
# ~/.codex/auth.json and routes through OpenAI's undocumented backend (ToS-gray). Review
# the proxy you use; this is for a single-user POC on your own subscription.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${WEBHOOK_PORT:-8085}"
PY="${PYTHON:-.venv/bin/python}"

USE_CODEX=0
SET_WEBHOOK=1
for arg in "$@"; do
  case "$arg" in
    --codex) USE_CODEX=1 ;;
    --no-webhook) SET_WEBHOOK=0 ;;
    *) echo "unknown arg: $arg  (use --codex and/or --no-webhook)"; exit 2 ;;
  esac
done

codex_pid=""; server_pid=""; tunnel_pid=""
cleanup() { kill "$server_pid" "$tunnel_pid" "$codex_pid" 2>/dev/null || true; }
trap cleanup INT TERM

# --- optional: Codex-subscription proxy ----------------------------------------
if [ "$USE_CODEX" = "1" ]; then
  CODEX_PROXY_PORT="${CODEX_PROXY_PORT:-10531}"
  CODEX_PROXY_CMD="${CODEX_PROXY_CMD:-npx -y openai-oauth --port $CODEX_PROXY_PORT}"
  if [ ! -f "$HOME/.codex/auth.json" ]; then
    echo "No ~/.codex/auth.json — run 'npx @openai/codex login' first."; exit 1
  fi
  if lsof -nP -iTCP:"$CODEX_PROXY_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Stopping process already on :$CODEX_PROXY_PORT ..."
    lsof -nP -tiTCP:"$CODEX_PROXY_PORT" -sTCP:LISTEN | xargs kill 2>/dev/null || true
    sleep 1
  fi
  echo "Starting Codex proxy: $CODEX_PROXY_CMD  -> /tmp/bott-codex-proxy.log"
  # shellcheck disable=SC2086
  $CODEX_PROXY_CMD >/tmp/bott-codex-proxy.log 2>&1 &
  codex_pid=$!
  for _ in $(seq 1 40); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$CODEX_PROXY_PORT/v1/models" || true)"
    [ "$code" != "000" ] && break
    if ! kill -0 "$codex_pid" 2>/dev/null; then
      echo "Codex proxy exited — see /tmp/bott-codex-proxy.log"; tail -20 /tmp/bott-codex-proxy.log; exit 1
    fi
    sleep 1
  done
  export REVIEW_MODEL_BASE_URL="http://127.0.0.1:$CODEX_PROXY_PORT/v1"
  echo "Codex proxy up on :$CODEX_PROXY_PORT (using your ChatGPT subscription)."

  # Reviewer runs on the Codex subscription (strong model); the manager runs a cheap/fast
  # model on the OpenAI API — so chat stays snappy and off the subscription. No prompt;
  # override either via env (REVIEW_MODEL / MANAGER_MODEL).
  export REVIEW_MODEL="${REVIEW_MODEL:-gpt-5.5}"
  export MANAGER_MODEL="${MANAGER_MODEL:-gpt-4.1-mini}"
  # Manager talks to the OpenAI API (MANAGER_MODEL_BASE_URL stays unset) and needs a key.
  echo "Review model  (Codex):  $REVIEW_MODEL"
  echo "Manager model (OpenAI): $MANAGER_MODEL"
  if [ -z "${OPENAI_API_KEY:-}" ] && ! grep -qE '^OPENAI_API_KEY=.+' .env 2>/dev/null; then
    echo "  note: the manager uses the OpenAI API — set OPENAI_API_KEY in .env, or set"
    echo "        MANAGER_MODEL_BASE_URL to run the manager on another endpoint."
  fi
fi

# --- stop any stale server on the webhook port ---------------------------------
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Stopping process already on :$PORT ..."
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi

echo "Starting bott server -> /tmp/bott-server.log"
"$PY" -m bott.interfaces.server >/tmp/bott-server.log 2>&1 &
server_pid=$!

for _ in $(seq 1 30); do
  curl -fsS -o /dev/null "http://localhost:$PORT/healthz" 2>/dev/null && break
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "Server exited during startup — see /tmp/bott-server.log"; tail -20 /tmp/bott-server.log; exit 1
  fi
  sleep 1
done
echo "Server healthy on :$PORT (pid=$server_pid)"

echo "Starting cloudflared tunnel -> /tmp/bott-tunnel.log"
cloudflared tunnel --url "http://localhost:$PORT" >/tmp/bott-tunnel.log 2>&1 &
tunnel_pid=$!

URL=""
for _ in $(seq 1 30); do
  URL="$(grep -aoE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/bott-tunnel.log | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -z "$URL" ] && { echo "Could not detect tunnel URL — see /tmp/bott-tunnel.log"; exit 1; }

code="$(curl -s -o /dev/null -w '%{http_code}' "$URL/healthz" || true)"
echo "Tunnel: $URL  (public /healthz -> $code)"

HOOK="$URL/webhook/github"
if [ "$SET_WEBHOOK" = "1" ]; then
  "$PY" scripts/set_app_webhook.py "$HOOK"
else
  echo "Register it on the GitHub App:  $PY scripts/set_app_webhook.py $HOOK"
fi

echo "Logs: /tmp/bott-server.log  /tmp/bott-tunnel.log${codex_pid:+  /tmp/bott-codex-proxy.log}"
echo "Ctrl-C to stop."
wait
