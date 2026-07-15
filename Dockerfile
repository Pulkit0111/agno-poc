# Bott — the Python app (agent + Slack + scheduler + PR-review worker + console API).
# Build:  docker build -t bott-app .
# Run:    docker run --env-file .env bott-app
#         (the entrypoint stamps/upgrades Alembic, then execs bott-app; the app listens
#          on BOTT_PORT, default 7777 — in production it is only reached over the docker
#          network by the console, never published to the host)

FROM python:3.12-slim AS base

# psycopg[binary] ships its own libpq; certifi (already a dependency) supplies CA certs —
# no extra system packages needed beyond what the slim base already has.
RUN pip install --no-cache-dir uv

# The `codex` CLI is THE model backend: every LLM call in bott (chat/build/review/triage/
# memory) shells out to `codex exec` on the org ChatGPT subscription, and the console's
# admin "Connect ChatGPT" flow (src/bott/shared/codex_login.py) runs `codex login
# --device-auth` in this same container. Auth lives solely in CODEX_HOME (a mounted
# volume — see docker-compose.prod.yml); the CLI owns and refreshes it.
# Pinned standalone musl binary from the official releases (no Node runtime needed).
ARG CODEX_VERSION=0.142.5
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64)  asset="codex-x86_64-unknown-linux-musl" ;; \
        aarch64) asset="codex-aarch64-unknown-linux-musl" ;; \
        *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/${asset}.tar.gz"; \
    python -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" "$url" /tmp/codex.tar.gz; \
    tar -xzf /tmp/codex.tar.gz -C /tmp; \
    install -m 0755 "/tmp/${asset}" /usr/local/bin/codex; \
    rm -f /tmp/codex.tar.gz "/tmp/${asset}"; \
    codex --version

WORKDIR /app

# Install dependencies first (separate layer — this only re-runs when the lockfile
# changes, not on every source edit).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY README.md ./README.md
RUN uv sync --frozen --no-dev

# Container default: bind all interfaces, not just loopback (BOTT_HOST=localhost is the
# right default for a laptop, but makes the service unreachable behind a container's
# network namespace). Override via env if you genuinely need loopback-only.
ENV BOTT_HOST=0.0.0.0
ENV PATH="/app/.venv/bin:${PATH}"
# The container runs as root; HOME must be writable because `codex login --device-auth`
# (the admin Connect flow above) writes ~/.codex/auth.json here before it is imported
# into Postgres. Set explicitly so a runtime that strips HOME can't break the login.
ENV HOME=/root

# Informational only — the app listens on BOTT_PORT at runtime (default 7777). Override
# the build arg if you want the image metadata to match a non-default port.
ARG BOTT_PORT=7777
EXPOSE ${BOTT_PORT}

# /readyz actually checks the database and background worker, not just "process is up"
# (see src/bott/interfaces/app.py) — a real liveness signal for the orchestrator.
# Reads BOTT_PORT at runtime so a .env override (e.g. 7788) is honored.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('BOTT_PORT','7777'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/readyz', timeout=4).status < 500 else 1)"

# Entrypoint stamps/upgrades the Alembic revision before starting the app (see the
# script header for the fresh-DB vs. migrated-DB logic), then execs the CMD — so plain
# `docker run ... bott-app` (or any other command) still works without compose.
COPY scripts/entrypoint.sh /usr/local/bin/bott-entrypoint.sh
RUN chmod +x /usr/local/bin/bott-entrypoint.sh
ENTRYPOINT ["bott-entrypoint.sh"]
CMD ["bott-app"]
