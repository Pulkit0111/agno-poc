# Bott — the Python app (agent + Slack + scheduler + PR-review worker + console API).
# Build:  docker build -t bott-app .
# Run:    docker run -p 7777:7777 --env-file .env bott-app

FROM python:3.12-slim AS base

# psycopg[binary] ships its own libpq; certifi (already a dependency) supplies CA certs —
# no extra system packages needed beyond what the slim base already has.
RUN pip install --no-cache-dir uv

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

EXPOSE 7777

# /readyz actually checks the database and background worker, not just "process is up"
# (see src/bott/interfaces/app.py) — a real liveness signal for the orchestrator.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:7777/readyz', timeout=4).status < 500 else 1)"

CMD ["bott-app"]
