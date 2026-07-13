"""Single source of truth for Bott's foundation tables (job queue, approvals, per-user
connector tokens, settings, dedup tables, review traces). Defined as SQLAlchemy Core so
both the runtime init helpers and Alembic share ONE schema definition — no drift. Runtime
DML still lives in the owning modules; this module owns only the table shapes."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy import text as _sql_text

METADATA = MetaData()

# Job queue (shared/persistence/queue.py owns the DML).
JOBS = Table(
    "jobs",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),
    Column("args", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=_sql_text("'pending'")),
    Column("attempts", Integer, nullable=False, server_default=_sql_text("0")),
    Column("dedup_key", Text),
    Column("error", Text),
    Column("created", Float, nullable=False),
    # Set when a job transitions to 'running' (claim_one). Lets orphan recovery (queue.py)
    # tell "genuinely still running on another instance" apart from "orphaned by a crash" —
    # a blanket `WHERE status='running'` on every boot would wrongly fail a job another,
    # still-alive instance is legitimately mid-way through.
    Column("claimed_at", Float, nullable=True),
)
Index("idx_jobs_pending", JOBS.c.status, JOBS.c.id)

# Human approval gate (shared/approvals.py owns the DML).
APPROVALS = Table(
    "approvals",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=_sql_text("'pending'")),
    Column("decided_by", Text),
    Column("payload", Text),  # JSON: parameters for the approved action (e.g. implement-job args)
    Column("created", Float, nullable=False),
)

# Per-user connector tokens (ciphertext at rest; one row per (user_id, provider)).
CONNECTOR_TOKENS = Table(
    "connector_tokens",
    METADATA,
    Column("user_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("token", Text, nullable=False),
    Column("created", Float),
    PrimaryKeyConstraint("user_id", "provider"),
)


# Key-value settings store (shared/persistence/records.py owns the DML).
SETTINGS = Table(
    "settings",
    METADATA,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

# GitHub webhook delivery dedup (shared/persistence/records.py owns the DML).
GITHUB_DELIVERIES = Table(
    "github_deliveries",
    METADATA,
    Column("delivery_id", Text, primary_key=True),
    Column("created", Float, nullable=False),
)

# Commit-level review dedup (shared/persistence/records.py owns the DML).
REVIEWED_COMMITS = Table(
    "reviewed_commits",
    METADATA,
    Column("repo_sha", Text, primary_key=True),
    Column("created", Float, nullable=False),
)

# Review traces for re-review continuity (shared/persistence/records.py owns the DML).
REVIEW_TRACES = Table(
    "review_traces",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", Text),
    Column("thread_ts", Text),
    Column("owner", Text),
    Column("name", Text),
    Column("pr_number", Integer),
    Column("original_verdict", Text),
    Column("final_verdict", Text),
    Column("output_json", Text),
    Column("gate_json", Text),
    Column("created", Float, nullable=False),
)
Index("idx_traces_thread", REVIEW_TRACES.c.channel, REVIEW_TRACES.c.thread_ts, REVIEW_TRACES.c.id)


# Authored skills (skills_store.py owns the DML). Source of truth for runtime-authored
# skills; materialized to the SKILL.md FS cache at startup. Curated in-repo skills have NO row.
SKILLS = Table(
    "skills",
    METADATA,
    Column("slug", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("authored_by", Text),
    Column("pinned", Integer, nullable=False, server_default=_sql_text("0")),
    Column("usage_count", Integer, nullable=False, server_default=_sql_text("0")),
    Column("created", Float, nullable=False),
    Column("updated", Float, nullable=False),
    Column("last_used", Float),
)


# Personal action items (shared/persistence/action_items.py owns the DML).
ACTION_ITEMS = Table(
    "action_items",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=_sql_text("'open'")),
    Column("remind_at", Float, nullable=True),
    Column("created", Float, nullable=False),
    Column("updated", Float, nullable=False),
    # Who/what created this item: "user" (agent tool), "console" (web console create),
    # "dsm" (auto-captured from a standup blocker). Drives console filtering/labeling.
    Column("source", Text, nullable=False, server_default=_sql_text("'user'")),
)
Index("idx_action_items_user_status", ACTION_ITEMS.c.user_id, ACTION_ITEMS.c.status)


# Personal console-only quick checklist (shared/persistence/todos.py owns the DML).
# Deliberately dumb — no Slack surface, no reminders, no admin variants. Distinct from
# ACTION_ITEMS above (which sync to Slack App Home and get DM reminders).
TODOS = Table(
    "todos",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("done", Integer, nullable=False, server_default=_sql_text("0")),
    Column("created", Float, nullable=False),
    Column("updated", Float, nullable=False),
)
Index("idx_todos_user", TODOS.c.user_id, TODOS.c.done, TODOS.c.id)


# Versioned prompt store (prompts_store.py owns the DML). Append-only history of
# IDENTITY/VOICE prompt edits; each save is a new row, never mutated in place.
PROMPT_VERSIONS = Table(
    "prompt_versions",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prompt_name", Text, nullable=False),  # "identity" | "voice"
    Column("content", Text, nullable=False),
    Column("note", Text),
    Column("author", Text, nullable=False),
    Column("created", Float, nullable=False),
)
Index("idx_prompt_versions_name", PROMPT_VERSIONS.c.prompt_name, PROMPT_VERSIONS.c.id)


# Versioned skill store (skills_store.py owns the DML). Append-only history of authored
# (non-built-in) skill content edits — mirrors PROMPT_VERSIONS' convention exactly.
SKILL_VERSIONS = Table(
    "skill_versions",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("note", Text),
    Column("author", Text, nullable=False),
    Column("created", Float, nullable=False),
)
Index("idx_skill_versions_slug", SKILL_VERSIONS.c.slug, SKILL_VERSIONS.c.id)


# Usage ledger for the shared org Codex account (codex_usage.py owns the DML). Not a
# billing meter — the ChatGPT subscription has no per-token price — this is a health
# signal: request/token volume over a rolling window, since the whole org shares one
# account's rate-limit pool and would otherwise have no warning before hitting it.
CODEX_USAGE = Table(
    "codex_usage",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text),
    Column("model_id", Text, nullable=False),
    Column("output_tokens", Integer, nullable=False, server_default=_sql_text("0")),
    Column("created", Float, nullable=False),
)
Index("idx_codex_usage_created", CODEX_USAGE.c.created)


# DSM/standup collection state (persistence/standup.py owns the DML). Used to live in a
# separate raw-sqlite3 file that ignored DATABASE_URL entirely — in production that meant
# writing to local disk instead of the shared database (lost on container recreation,
# invisible to any other replica). Moved onto the same shared engine as everything else.
STANDUP_ROUNDS = Table(
    "standup_rounds",
    METADATA,
    Column("team", Text, nullable=False),
    Column("date", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("thread_ts", Text, nullable=False),
    Column("created", Float, nullable=False),
    PrimaryKeyConstraint("team", "date"),
)

STANDUP_RESPONSES = Table(
    "standup_responses",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("team", Text, nullable=False),
    Column("date", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("yesterday", Text),
    Column("today", Text),
    Column("blockers", Text),
    Column("created", Float, nullable=False),
)
Index("idx_standup_responses", STANDUP_RESPONSES.c.team, STANDUP_RESPONSES.c.date,
      STANDUP_RESPONSES.c.id)


def init_schema(engine=None) -> None:
    """Create all foundation tables if absent (idempotent). The dev/test fast path;
    production schema EVOLUTION goes through Alembic, which targets this same METADATA."""
    from bott.shared.db import get_engine

    METADATA.create_all(engine or get_engine())
