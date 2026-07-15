"""Configuration for the review POC — env, model, budget caps, thresholds.

Secrets come from the environment (.env loaded by the entrypoints), never hardcoded.
"""

from __future__ import annotations

import os
import re as _re
import shutil
from dataclasses import dataclass

# Diff assembly caps (port of fetch-pr-essentials.ts).
DIFF_CAP = 16_000
PER_FILE_PATCH_CAP = 4_000

# One agent, one LLM. BOTT_MODEL is the single source of truth (default gpt-5.5).
# MANAGER_MODEL / REVIEW_MODEL are kept ONLY as deprecated fallbacks so existing .env files
# keep working — there is no separate manager/review model and no store-setting override.
def bott_model() -> str:
    return os.getenv("BOTT_MODEL") or os.getenv("MANAGER_MODEL") or os.getenv("REVIEW_MODEL") or "gpt-5.5"


# Back-compat alias (used as a default arg in the review engine); resolves to the single model.
DEFAULT_MODEL = bott_model()

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
def _github_app_env_credentials() -> dict | None:
    """The GITHUB_APP_* env vars, as a bundle (installation_id is env-less: the env-based
    flow discovers the installation per-repo via the GitHub API instead of pinning one)."""
    app_id = os.getenv("GITHUB_APP_ID")
    pem = os.getenv("GITHUB_APP_PRIVATE_KEY")
    if pem:
        pem = pem.replace("\\n", "\n")
    else:
        path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
        if path and os.path.exists(path):
            with open(path) as f:
                pem = f.read()
    if app_id and pem:
        return {"app_id": app_id, "installation_id": None, "private_key": pem}
    return None


def github_app_credentials() -> dict | None:
    """GitHub App credentials as ``{app_id, installation_id, private_key}``: the console's
    encrypted credential store FIRST (added via POST /connectors/add, key ``'github-app'``),
    falling back to the ``GITHUB_APP_ID`` / ``GITHUB_APP_PRIVATE_KEY[_PATH]`` env vars.

    This is the single source of truth ``github_app_id()`` / ``github_app_private_key()``
    (and therefore ``github_app_configured()``) resolve through below — and it's what
    ``app_auth.py``'s JWT/installation-token minting reads (via those two functions), on
    EVERY call, with no caching of the credentials themselves. So adding or removing a
    GitHub App from the console takes effect on the very next request — no restart.
    (``app_auth.py`` does cache MINTED installation tokens per owner/repo for ~55 minutes;
    a credential change doesn't invalidate an already-minted, still-fresh token early — it
    governs the next mint, which is a bounded, acceptable staleness window, not a "restart
    required" one.)"""
    from bott.shared import connector_credentials
    stored = connector_credentials.load("github-app")
    if stored:
        return stored
    return _github_app_env_credentials()


def github_app_id() -> str | None:
    creds = github_app_credentials()
    return creds.get("app_id") if creds else None


def github_app_private_key() -> str | None:
    """PEM contents — store first, else GITHUB_APP_PRIVATE_KEY / _PATH. See
    ``github_app_credentials()`` for the live-without-restart contract."""
    creds = github_app_credentials()
    return creds.get("private_key") if creds else None


def github_webhook_secret() -> str | None:
    return os.getenv("GITHUB_WEBHOOK_SECRET")


def allowed_post_repos() -> set[str]:
    """Allowlist of owner/name repos the bot may post reviews to (constraint #3)."""
    raw = os.getenv("ALLOWED_POST_REPOS", "")
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def review_slack_channel() -> str | None:
    """Channel to mirror auto-triggered (webhook) reviews into, if set."""
    return os.getenv("REVIEW_SLACK_CHANNEL")


def build_draft_pr() -> bool:
    """Whether Build & Fix opens PRs as drafts. Default False — open ready-for-review PRs
    (users found forced drafts annoying). Set BUILD_DRAFT_PR=1 to restore draft PRs."""
    return os.getenv("BUILD_DRAFT_PR", "0").strip().lower() in ("1", "true", "yes")


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


def _codex_proxy_base_url() -> str:
    """The local Codex proxy's OpenAI-compatible endpoint, derived from CODEX_PROXY_PORT."""
    return f"http://127.0.0.1:{codex_proxy_port()}/v1"


def model_base_url() -> str | None:
    """Endpoint for the reviewer model. In codex backend mode it's DERIVED from CODEX_PROXY_PORT
    (the single source of truth) so a second instance on a different proxy port can't call the
    wrong port — a hardcoded REVIEW_MODEL_BASE_URL is ignored in codex mode. In openai mode it's
    the custom endpoint env (Azure/OpenRouter/etc.) or None → api.openai.com."""
    if model_backend() == "codex":
        return _codex_proxy_base_url()
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
    """Deprecated — one agent, one model now. Resolves to the single bott_model()."""
    return bott_model()


def manager_base_url() -> str | None:
    """Endpoint for the manager (chat) model. In codex backend mode it's DERIVED from
    CODEX_PROXY_PORT (single source of truth — see model_base_url), so multi-instance setups
    never drift to a stale hardcoded port. In openai mode it's MANAGER_MODEL_BASE_URL or None."""
    if model_backend() == "codex":
        return _codex_proxy_base_url()
    return os.getenv("MANAGER_MODEL_BASE_URL") or None


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


def confluence_url() -> str | None:
    """Confluence base — explicit CONFLUENCE_URL, else the Jira site + /wiki (same Atlassian Cloud)."""
    v = os.getenv("CONFLUENCE_URL")
    if v:
        return v.rstrip("/")
    base = jira_base_url()
    return f"{base}/wiki" if base else None


def confluence_username() -> str | None:
    return os.getenv("CONFLUENCE_USERNAME") or jira_email()


def confluence_api_key() -> str | None:
    return os.getenv("CONFLUENCE_API_KEY") or jira_api_token()


def confluence_configured() -> bool:
    return bool(confluence_url() and confluence_username() and confluence_api_key())


# --- Sentry (read-only incident/error data) ------------------------------------
def sentry_base_url() -> str | None:
    """Sentry instance base (default SaaS)."""
    v = os.getenv("SENTRY_BASE_URL", "https://sentry.io")
    return v.rstrip("/") if v else None


def sentry_org_slug() -> str | None:
    return os.getenv("SENTRY_ORG_SLUG") or None


def sentry_api_token() -> str | None:
    return os.getenv("SENTRY_API_TOKEN") or None


def sentry_configured() -> bool:
    return bool(sentry_org_slug() and sentry_api_token())


def sentry_org_credentials(name: str) -> dict | None:
    """Credentials for an ADDITIONAL Sentry org added from the console (key
    ``'sentry-<name>'`` in the credential store), as ``{org, auth_token, base_url}``.
    Store-only — no env fallback: the ONE default org already has its own env-based path
    above (``sentry_org_slug()`` / ``sentry_api_token()`` / ``sentry_base_url()``),
    untouched by this. Read fresh on every call, so a console add/remove is live
    immediately for anything that calls this per-request (the console's probe/test button).

    IMPORTANT caveat this does NOT solve: the Sentry read tools/skill registered onto the
    agent are wired ONCE, at agent-build time, from the single env-configured org above —
    adding a second org's credentials here does not register a second set of Sentry tools.
    That's future work (per-org tool wiring), same restart/rebuild caveat as retiring a
    skill. Today, storing a second org's credentials here only makes them
    probeable/testable from the console — nothing in the agent's tool list points at them
    yet."""
    from bott.shared import connector_credentials
    key = (name or "").strip().lower()
    if not key:
        return None
    return connector_credentials.load(f"sentry-{key}")


def google_service_account_path() -> str | None:
    """Path to the Google service-account JSON key used for domain-wide delegation."""
    return os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH") or None


def google_delegation_configured() -> bool:
    """True when a service-account key file is configured and present on disk."""
    p = google_service_account_path()
    return bool(p) and os.path.exists(p)


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
    """The zone public deploys are served on: <subdomain>.<zone>/. A blank env value falls
    back to the default (a set-but-empty SPIN_PUBLIC_ZONE previously produced `<slug>.` URLs)."""
    return os.getenv("SPIN_PUBLIC_ZONE") or "public.spin.axelerant.tech"


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
# Read-only file/text inspection only. Interpreters (python/python3) are deliberately EXCLUDED:
# the workspace shell must not be a code-execution or network-egress path (e.g. `python -c
# "import urllib; urllib.request.urlopen(...)"` would reach the network unmediated by the
# action policy that guards the http/slack/github/atlassian connectors). curl/wget are absent
# for the same reason. Override with BOTT_SHELL_ALLOWED_COMMANDS if an operator needs more.
_DEFAULT_SHELL_ALLOWLIST = ["ls", "cat", "echo", "pwd", "head", "tail", "grep", "find", "wc"]


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


# --- Foundation: model provider + per-role routing -----------------------------
def model_provider() -> str:
    """'codex' (dev proxy), 'bedrock', or 'openrouter' (prod). One global provider."""
    return (os.getenv("MODEL_PROVIDER") or "codex").strip().lower()


def role_model_id(role: str) -> str:
    """Per-task model id. Roles: 'chat' (everyday) · 'build' (plan/implement/triage) ·
    'review' (PR review — should DIFFER from build so the reviewer doesn't share the
    author's blind spots) · 'heavy' (legacy tier build/review fall back to).
    Fallback chain: own env → heavy tier → the single BOTT_MODEL. Unknown roles → chat."""
    heavy = os.getenv("BOTT_HEAVY_MODEL") or bott_model()
    if role == "build":
        return os.getenv("BOTT_BUILD_MODEL") or heavy
    if role == "review":
        return os.getenv("BOTT_REVIEW_MODEL") or heavy
    if role == "heavy":
        return heavy
    return os.getenv("BOTT_CHAT_MODEL") or bott_model()


def database_url() -> str | None:
    return os.getenv("DATABASE_URL") or None


def bott_secret_key() -> str | None:
    """Fernet key for SecretBox (urlsafe base64, 32 bytes). Env in dev; vault/KMS later."""
    return os.getenv("BOTT_SECRET_KEY") or None


def openrouter_api_key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY") or None


def fallback_model_provider() -> str | None:
    """Optional secondary provider (`bedrock` or `openrouter`) build_model() switches to
    when the primary provider is `codex` and the shared org login is broken (token missing,
    refresh failed). Unset by default: no fallback, so a Codex outage surfaces as a clear
    error — plus an admin alert — instead of silently degrading to a different model with
    nobody told. Set FALLBACK_MODEL_PROVIDER=bedrock (or openrouter) to opt in."""
    v = (os.getenv("FALLBACK_MODEL_PROVIDER") or "").strip().lower()
    return v or None


# Sane, capable defaults if a fallback provider is enabled but FALLBACK_MODEL_ID isn't set —
# these are provider-specific ids, unlike the codex model ids in BOTT_*_MODEL, so they can't
# just reuse whatever's already configured for the primary (codex) provider.
_FALLBACK_MODEL_DEFAULTS: dict[str, str] = {
    "bedrock": "anthropic.claude-sonnet-4-6-v1:0",
    "openrouter": "anthropic/claude-sonnet-4.6",
}


def fallback_model_id(provider: str) -> str:
    return os.getenv("FALLBACK_MODEL_ID") or _FALLBACK_MODEL_DEFAULTS.get(provider, "")


# --- Build-fix: implement pipeline budget -------------------------------------
@dataclass
class ImplementBudget:
    max_fix_attempts: int = 4
    max_tool_calls: int = 40
    timeout_s: int = 900


def implement_budget() -> "ImplementBudget":
    return ImplementBudget(
        max_fix_attempts=int(os.getenv("BUILD_MAX_FIX_ATTEMPTS", "4")),
        max_tool_calls=int(os.getenv("BUILD_MAX_TOOL_CALLS", "40")),
        timeout_s=int(os.getenv("BUILD_TIMEOUT_S", "900")),
    )


def _build_branch_name(plan_text: str) -> str:
    slug = _re.sub(r"[^a-z0-9]+", "-", (plan_text or "change").lower()).strip("-")[:32] or "change"
    # short, unique-per-process suffix: Python's hash() is PRNG-seeded per process (PYTHONHASHSEED),
    # so it is NOT stable across restarts — same text can produce a different suffix in a new process.
    # That's fine: the goal is intra-process branch-name uniqueness, not cross-process determinism.
    suffix = format(abs(hash(plan_text)) % 0xFFFFFF, "x")
    return f"bott/{slug}-{suffix}"


# --- Codex (org-level ChatGPT subscription) ------------------------------------
def codex_client_id() -> str:
    return os.getenv("CODEX_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")


def codex_token_endpoint() -> str:
    return os.getenv("CODEX_TOKEN_ENDPOINT", "https://auth.openai.com/api/accounts/oauth/token")


def codex_backend_base_url() -> str:
    return os.getenv("CODEX_BACKEND_BASE_URL", "https://chatgpt.com/backend-api/codex")


def codex_refresh_margin_s() -> int:
    return int(os.getenv("CODEX_REFRESH_MARGIN_S", "300"))


def codex_timeout_s() -> float:
    """Total per-request ceiling (read/write/pool) for one Codex backend call; connect is
    capped separately (~10s) in codex_model. Without this the OpenAI client runs with NO
    timeout — a single hung upstream stream hangs forever while holding one of the few
    org-wide concurrency slots (codex_max_concurrent_requests), so a handful of hung calls
    freezes chat for the whole org. Generous by default: heavy build/review responses
    stream for minutes."""
    return float(os.getenv("CODEX_TIMEOUT_S", "300"))


def codex_max_concurrent_requests() -> int:
    """Org-wide cap on simultaneous in-flight Codex calls. Everyone shares ONE ChatGPT
    subscription, so a burst of concurrent Slack messages from different users must queue
    behind this cap instead of all hitting the backend at once and 429ing each other."""
    return int(os.getenv("CODEX_MAX_CONCURRENT_REQUESTS", "4"))


def codex_max_concurrent_per_user() -> int:
    """Per-user cap, smaller than the org-wide one, so a single heavy user (or a runaway
    loop) can't claim every concurrent slot and starve everyone else's share."""
    return int(os.getenv("CODEX_MAX_CONCURRENT_PER_USER", "2"))


def job_orphan_stale_after_s() -> int:
    """How long a job may sit in 'running' before orphan recovery (queue.py) is willing to
    fail it as crashed. Must exceed the longest legitimate job runtime — otherwise a
    still-genuinely-running job (this instance's own, or another instance's under multi-
    replica deployment) gets wrongly marked failed mid-way through. Default (30 min) gives
    real margin over BUILD_TIMEOUT_S's own default (900s / 15 min)."""
    return int(os.getenv("JOB_ORPHAN_STALE_AFTER_S", "1800"))


def model_retry_delay_s() -> int:
    """Base delay (seconds) between retries on a transient provider error, doubled each
    attempt (see model.py's _COMMON). The old default of 1s (1/2/4s across 3 retries — 7s
    total) is sized for a personal API key's rate limits, not a whole org sharing ONE
    ChatGPT subscription, where a 429 often means "wait tens of seconds," not one."""
    return int(os.getenv("MODEL_RETRY_DELAY_S", "3"))


def bott_admins() -> set[str]:
    """Emails allowed to connect the org Codex account / override the model (csv)."""
    return {e.strip().lower() for e in os.getenv("BOTT_ADMINS", "").split(",") if e.strip()}


# --- Codex CLI-exec (route build/review through the official `codex` binary) --
def codex_cli_enabled() -> bool:
    """Route build/review through the official `codex` CLI subprocess (codex exec) instead
    of Agno's tool-calling loop, mirroring how a known-production reference app runs Codex —
    the CLI's own request shape/telemetry is indistinguishable from a human running it
    interactively, which is materially lower ban-risk than hitting the internal Responses API
    directly (see codex_model.py). Off by default: opt in only after verifying the `codex`
    binary + its bubblewrap sandbox actually work in the target deploy environment."""
    return os.getenv("CODEX_CLI_EXEC", "0").strip().lower() in ("1", "true", "yes")


def codex_cli_binary() -> str:
    return os.getenv("CODEX_CLI_BIN", "codex")


def codex_cli_home() -> str:
    """The persistent directory the `codex` CLI keeps its login in (`auth.json`) — the SAME
    home for every `codex exec` call, exactly like the reference deployment (a mounted volume
    in the container; `~/.codex` in local dev). An org admin runs `codex login` once to
    populate it; the CLI then owns the token entirely (reading + refreshing + rotating it in
    place, with its own file locking), so many users' build/review calls share one login
    safely — bott never copies, writes, or reconciles the token itself. `CODEX_HOME` overrides
    the path (set it to the mounted volume in production)."""
    return os.getenv("CODEX_HOME") or os.path.expanduser("~/.codex")


def codex_cli_timeout_s() -> int:
    return int(os.getenv("CODEX_CLI_TIMEOUT_S", "900"))


def codex_chat_timeout_s() -> int:
    """Per-turn ceiling for CHAT codex exec calls — much tighter than the build/review
    ceiling (codex_cli_timeout_s): a person is sitting in Slack waiting for this one."""
    return int(os.getenv("CODEX_CHAT_TIMEOUT_S", "300"))


def codex_cli_disable_sandbox() -> bool:
    """In a container, codex's bubblewrap sandbox needs unprivileged user namespaces, which
    are often disabled (hardened kernels, restrictive container runtimes) — codex exec would
    simply fail to start there. Docker is already the real isolation boundary in prod, so
    when this is on, callers swap the CLI's `-s <sandbox>` flag for
    `--dangerously-bypass-approvals-and-sandbox` instead. Off by default: dev on macOS uses
    the real sandbox, and this should only be flipped on for the containerized deploy where
    bubblewrap is verified to be unusable."""
    return os.getenv("BOTT_CODEX_DISABLE_SANDBOX", "0").strip().lower() in ("1", "true", "yes")
