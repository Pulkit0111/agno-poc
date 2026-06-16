"""Configuration for the review POC — env, model, budget caps, thresholds.

Secrets come from the environment (.env loaded by the entrypoints), never hardcoded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Diff assembly caps (port of fetch-pr-essentials.ts).
DIFF_CAP = 16_000
PER_FILE_PATCH_CAP = 4_000

# gpt-4.1-mini: 1M-token context (vs gpt-4o-mini's 128k) + faster. Override via env.
DEFAULT_MODEL = os.getenv("REVIEW_MODEL", "gpt-4.1-mini")


@dataclass
class Budget:
    """Hard caps for one review run (port of budget.ts FALLBACK_BUDGET)."""

    max_tool_calls: int = 30
    max_tokens: int = 200_000
    max_usd: float = 0.50


def default_budget() -> "Budget":
    """Per-review budget from env (sane defaults tuned for low OpenAI TPM tiers)."""
    return Budget(
        max_tool_calls=int(os.getenv("REVIEW_MAX_TOOL_CALLS", "12")),
        max_tokens=int(os.getenv("REVIEW_MAX_TOKENS", "200000")),
        max_usd=float(os.getenv("REVIEW_MAX_USD", "0.50")),
    )


@dataclass
class GateThresholds:
    """Verdict-gate tuning knobs (ported from Bott). Defaults reproduce the original
    hardcoded behavior; override via env for per-deployment tuning without code changes."""

    large_diff_files: int = 5
    large_diff_lines: int = 200
    min_lookups_for_large: int = 3
    substantive_new_file_lines: int = 50


def gate_thresholds() -> "GateThresholds":
    """Verdict-gate thresholds, env-overridable (defaults preserve prior behavior)."""
    return GateThresholds(
        large_diff_files=int(os.getenv("REVIEW_LARGE_DIFF_FILES", "5")),
        large_diff_lines=int(os.getenv("REVIEW_LARGE_DIFF_LINES", "200")),
        min_lookups_for_large=int(os.getenv("REVIEW_MIN_LOOKUPS_FOR_LARGE", "3")),
        substantive_new_file_lines=int(os.getenv("REVIEW_SUBSTANTIVE_NEW_FILE_LINES", "50")),
    )


def db_path() -> str:
    """Path to the SQLite task/trace DB. Overridable for deployments and tests;
    defaults to the original repo-root filename for backward compatibility."""
    return os.getenv("REVIEW_DB_PATH", "review_poc.db")


# USD per 1M tokens (port of Bott's model-cost table; Agno doesn't populate
# `metrics.cost` for every model, so we compute it ourselves for the cost axis).
MODEL_COSTS: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.0},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
}


def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """USD cost for a run. Cached-read tokens are billed at the cached rate and
    are assumed included in `input_tokens` (so we discount the delta)."""
    rates = MODEL_COSTS.get(model_id)
    if rates is None:
        return None
    in_rate = rates["input"] / 1_000_000
    cached_rate = rates.get("cached_input", rates["input"]) / 1_000_000
    out_rate = rates["output"] / 1_000_000
    uncached_in = max(0, input_tokens - cache_read_tokens)
    return (
        uncached_in * in_rate
        + cache_read_tokens * cached_rate
        + output_tokens * out_rate
    )


def github_token() -> str | None:
    """Optional token to raise GitHub's 60/hr unauthenticated rate limit (phase 1)."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("BOTT_POC_GITHUB_TOKEN")


# --- Phase 3: GitHub App + webhook ---------------------------------------------
def github_app_id() -> str | None:
    return os.getenv("GITHUB_APP_ID")


def github_app_private_key() -> str | None:
    """PEM contents, or read from GITHUB_APP_PRIVATE_KEY_PATH."""
    pem = os.getenv("GITHUB_APP_PRIVATE_KEY")
    if pem:
        return pem.replace("\\n", "\n")
    path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read()
    return None


def github_webhook_secret() -> str | None:
    return os.getenv("GITHUB_WEBHOOK_SECRET")


def allowed_post_repos() -> set[str]:
    """Allowlist of owner/name repos the bot may post reviews to (constraint #3)."""
    raw = os.getenv("ALLOWED_POST_REPOS", "")
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def review_slack_channel() -> str | None:
    """Channel to mirror auto-triggered (webhook) reviews into, if set."""
    return os.getenv("REVIEW_SLACK_CHANNEL")


def github_app_configured() -> bool:
    return bool(github_app_id() and github_app_private_key())


def validate_required() -> list[str]:
    """Problems with required config (empty list = OK). Checked at startup so we
    fail fast with clear messages instead of crashing mid-request."""
    problems: list[str] = []
    # Model auth: a key (OpenAI or an explicit override) OR a custom base_url
    # (e.g. a local OpenAI-compatible proxy that carries its own auth).
    if not model_api_key() and not model_base_url():
        problems.append(
            "No model auth — set OPENAI_API_KEY (or REVIEW_MODEL_API_KEY), or point "
            "REVIEW_MODEL_BASE_URL at an OpenAI-compatible endpoint that carries its own auth."
        )
    if not os.getenv("SLACK_BOT_TOKEN"):
        problems.append("SLACK_BOT_TOKEN is not set — Slack is the primary interface.")
    if not os.getenv("SLACK_APP_TOKEN"):
        problems.append("SLACK_APP_TOKEN is not set — required for Slack Socket Mode.")
    return problems


def openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY")


def model_base_url() -> str | None:
    """Custom OpenAI-compatible endpoint (Azure/OpenRouter/local model/Codex-subscription
    proxy). When set, the app talks here instead of api.openai.com."""
    return os.getenv("REVIEW_MODEL_BASE_URL") or None


def model_api_key() -> str | None:
    """Key for the model endpoint: an explicit override, else the standard OpenAI key."""
    return os.getenv("REVIEW_MODEL_API_KEY") or os.getenv("OPENAI_API_KEY") or None
