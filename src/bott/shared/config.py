"""Configuration for the review POC — env, model, budget caps, thresholds.

Secrets come from the environment (.env loaded by the entrypoints), never hardcoded.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

# Diff assembly caps (port of fetch-pr-essentials.ts).
DIFF_CAP = 16_000
PER_FILE_PATCH_CAP = 4_000

# gpt-4.1-mini: 1M-token context (vs gpt-4o-mini's 128k) + faster. Override via env.
DEFAULT_MODEL = os.getenv("REVIEW_MODEL", "gpt-4.1-mini")

# Setting keys for the shared settings KV (dashboard-selected models).
SETTING_MANAGER_MODEL = "manager_model"
SETTING_REVIEWER_MODEL = "reviewer_model"

# Fallback model list for the dashboard picker when the Codex proxy can't be queried.
# These are the models the Codex-subscription proxy typically exposes.
FALLBACK_CODEX_MODELS = [
    "gpt-5.5",
    "gpt-5.5-codex",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5-codex",
]


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


def agentos_db_path() -> str:
    """Path to the shared Agno SqliteDb that backs AgentOS sessions/metrics and (now)
    Slack sessions. Separate from the worker's task/trace DB (review_poc.db)."""
    return os.getenv("AGENTOS_DB_PATH", "agentos.db")


def agentos_jwt_secret() -> str | None:
    """Shared HS256 secret the Next.js BFF signs with and AgentOS verifies. Required to
    enable API auth; when unset, the API runs open (local dev only)."""
    return os.getenv("AGENT_OS_JWT_SECRET") or None


def allowed_email_domain() -> str:
    """Workspace domain allowed to access the dashboard/API."""
    return os.getenv("ALLOWED_EMAIL_DOMAIN", "axelerant.com")


# --- Memra (read-only context layer over MCP) ----------------------------------
def memra_client_id() -> str | None:
    return os.getenv("MEMRA_CLIENT_ID") or None


def memra_client_secret() -> str | None:
    return os.getenv("MEMRA_CLIENT_SECRET") or None


def memra_token_endpoint() -> str:
    return os.getenv("MEMRA_TOKEN_ENDPOINT", "https://memra.team/oauth/token")


def memra_mcp_endpoint() -> str:
    return os.getenv("MEMRA_MCP_ENDPOINT", "https://memra.team/api/mcp")


def memra_scope() -> str:
    return os.getenv("MEMRA_SCOPE", "mcp:retrieve:internal")


def memra_configured() -> bool:
    return bool(memra_client_id() and memra_client_secret())


# --- Model backend (pluggable: Codex subscription for dev, sanctioned key for prod) ---
def model_backend() -> str:
    """'codex' (default; single-user POC via the auto-started Codex proxy) or 'openai'
    (sanctioned api.openai.com key, for multi-user production)."""
    return os.getenv("MODEL_BACKEND", "codex").strip().lower()


def codex_proxy_port() -> int:
    return int(os.getenv("CODEX_PROXY_PORT", "10531"))


def codex_proxy_cmd() -> str:
    """Override the proxy command if needed; default is built by the manager."""
    return os.getenv("CODEX_PROXY_CMD", "")


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


_GH_CLI_TOKEN_SENTINEL = object()
_gh_cli_token_cache: object = _GH_CLI_TOKEN_SENTINEL


def _gh_cli_token() -> str | None:
    """The locally-authenticated `gh` CLI's token (dev fallback), looked up once per process.
    Returns None when `gh` isn't installed or isn't logged in. Lets the POC reuse your existing
    `gh` login instead of a separate env var — same spirit as the Codex backend. Not for a
    deployed/multi-user Bott (use a scoped PAT or the GitHub App there)."""
    global _gh_cli_token_cache
    if _gh_cli_token_cache is not _GH_CLI_TOKEN_SENTINEL:
        return _gh_cli_token_cache  # type: ignore[return-value]
    val: str | None = None
    if shutil.which("gh"):
        try:
            import subprocess

            r = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
            )
            val = (r.stdout or "").strip() or None
        except Exception:  # noqa: BLE001 — gh missing/unauthed/slow → just no token
            val = None
    _gh_cli_token_cache = val
    return val


def github_token() -> str | None:
    """Token for GitHub reads (raises the 60/hr unauthenticated limit; powers the read-only
    GitHub tools). Env vars win; otherwise fall back to the local `gh` CLI's token so the POC
    reuses your existing `gh` login with no extra setup."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("BOTT_POC_GITHUB_TOKEN") or _gh_cli_token()


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


def review_temperature() -> float | None:
    """Optional sampling temperature for the reviewer, for reproducible verdicts. Unset by
    default — gpt-5 reasoning models (the Codex-proxy default) reject temperature != 1, so we
    only pass it when explicitly configured (e.g. on a model that supports temperature=0)."""
    v = os.getenv("REVIEW_TEMPERATURE")
    if v is None or v.strip() == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def manager_model() -> str:
    """Model for the conversational manager (chat + routing). A fast/cheap model is plenty
    here — the heavy review runs separately on REVIEW_MODEL. Falls back to the review model
    when MANAGER_MODEL isn't set, so behavior is unchanged unless you opt in."""
    return os.getenv("MANAGER_MODEL") or DEFAULT_MODEL


def manager_base_url() -> str | None:
    """Endpoint for the manager model. Independent of the reviewer's, so the manager can run
    a cheap model on the OpenAI API (default: unset → api.openai.com) while the reviewer uses
    a Codex-subscription proxy."""
    return os.getenv("MANAGER_MODEL_BASE_URL") or None


def manager_api_key() -> str | None:
    """Key for the manager endpoint: an explicit override, else the standard OpenAI key."""
    return os.getenv("MANAGER_MODEL_API_KEY") or os.getenv("OPENAI_API_KEY") or None


# --- Jira (live sprint data for the sprint-report skill) ------------------------
def jira_base_url() -> str | None:
    """Jira Cloud site, e.g. https://axelerant.atlassian.net (no trailing slash)."""
    v = os.getenv("JIRA_BASE_URL")
    return v.rstrip("/") if v else None


def jira_email() -> str | None:
    """Account email for Jira Cloud basic auth (paired with an API token)."""
    return os.getenv("JIRA_EMAIL") or None


def jira_api_token() -> str | None:
    return os.getenv("JIRA_API_TOKEN") or None


def jira_configured() -> bool:
    return bool(jira_base_url() and jira_email() and jira_api_token())


def jira_story_points_field() -> str | None:
    """Jira Cloud has ONE story-points custom field site-wide. Pin it here to skip
    auto-detection (e.g. JIRA_STORY_POINTS_FIELD=customfield_10016); when unset, the
    client detects it once from Jira's field catalogue."""
    return os.getenv("JIRA_STORY_POINTS_FIELD") or None


# --- Spin (publishing the rendered report as a hosted static page) --------------
# Spin's headless path is the Platform API (Bearer key); the MCP endpoint is OAuth-only.
# A public deploy is served at https://<subdomain>.<public-zone>/.
def spin_api_base_url() -> str:
    return (os.getenv("SPIN_API_BASE_URL") or "https://platform-api.spin.axelerant.tech").rstrip("/")


def spin_api_token() -> str | None:
    return os.getenv("SPIN_API_TOKEN") or None


def spin_public_zone() -> str:
    """The zone public deploys are served on: <subdomain>.<zone>/."""
    return os.getenv("SPIN_PUBLIC_ZONE", "public.spin.axelerant.tech")


def spin_configured() -> bool:
    """True when headless Spin publishing is possible (a Platform API key is set); else the
    skill falls back to posting the report to Slack."""
    return bool(spin_api_token())


# --- Sprint-report overrides (OPTIONAL) -----------------------------------------
# Sprint reports work for ANY engagement with no config: Bott discovers the Jira board
# by project key/name and derives the title/slug from the project. This dict is only for
# the occasional engagement that wants a custom title, slug, or a pinned channel — keyed
# by Jira project key (case-insensitive). Leave it empty to rely entirely on discovery.
#
#   "PADI": {"title": "PADI Digital Overhaul", "channel": "#padi"}
#
SPRINT_REPORT_OVERRIDES: dict[str, dict] = {}


def sprint_report_override(project_key: str) -> dict:
    return SPRINT_REPORT_OVERRIDES.get((project_key or "").strip().upper(), {})


# --- Agentic skills layer (Hermes-style) ---------------------------------------
_DEFAULT_SHELL_ALLOWLIST = ["ls", "cat", "echo", "pwd", "head", "tail", "grep", "find", "wc", "python", "python3"]


def bott_skills_dir() -> str:
    """Directory holding the SKILL.md library (Agent Skills standard). In-repo + tracked."""
    return os.getenv("BOTT_SKILLS_DIR") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", "library")


def bott_workspace_dir() -> str:
    """Sandboxed scratch dir the file/terminal/code tools are fenced to. Gitignored."""
    return os.getenv("BOTT_WORKSPACE_DIR", ".bott_workspace")


def bott_shell_allowed_commands() -> list[str]:
    """Allowlist for the workspace shell. Override via BOTT_SHELL_ALLOWED_COMMANDS (csv)."""
    raw = os.getenv("BOTT_SHELL_ALLOWED_COMMANDS")
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(_DEFAULT_SHELL_ALLOWLIST)
