"""Single place the LLM is built — codex-only: every role runs on the org ChatGPT
subscription through the official codex CLI (CodexExecChat / codex_cli.run_codex_exec).

Roles: 'chat' (everyday) vs 'build'/'review' ('heavy' legacy tier as fallback). The
per-role PROVIDER switching layer (OpenRouter/Bedrock) is gone; per-role MODEL IDS remain
(resolve_model_id). Review and build may share the strongest model — anti-affinity was
removed (see _review_anti_affinity)."""

from __future__ import annotations

from bott.shared.observability.logging_setup import get_logger

from .config import (
    model_provider,
    model_retry_delay_s,
    role_model_id,
)

log = get_logger("bott.model")

_COMMON = {
    "retries": 3,
    "exponential_backoff": True,
    "delay_between_retries": model_retry_delay_s(),
}


def _setting(key: str):
    """Admin override from the Postgres settings store; None if unset/unavailable."""
    try:
        from bott.shared.persistence.records import get_setting
        return get_setting(key)
    except Exception:  # noqa: BLE001 — settings store optional at construction time
        return None


def _codex_id(value, key: str):
    """Reject stored model ids that can't be codex ids. OpenRouter ids are
    'vendor/model' — a ChatGPT-account codex login rejects them with a 400, so a stale
    row left over from the removed provider layer would break every call for that role
    (observed live: chat pinned to 'poolside/laguna-m.1:free'). Ignore with a warning
    and fall through to the env default instead."""
    if value and "/" in value:
        log.warning("ignoring stale non-codex model id %r in settings key %s — "
                    "bott is codex-only; falling back to the env default", value, key)
        return None
    return value


def resolve_model_id(role: str) -> str:
    """The model id a role resolves to right now (admin settings-store override → env
    fallback chain). build/review also honor a legacy `model.heavy` store override."""
    direct = _codex_id(_setting(f"model.{role}"), f"model.{role}")
    if direct:
        return direct
    if role in ("build", "review"):
        legacy = _codex_id(_setting("model.heavy"), "model.heavy")
        if legacy:
            return legacy
    return role_model_id(role)


def resolve_provider(role: str) -> str:
    """Always "codex" — bott is codex-only. Kept (with its signature) because call sites
    and older settings rows still reference it; stale `model.provider*` store overrides
    and MODEL_PROVIDER env values are deliberately ignored (with a log) rather than
    honored or crashed on."""
    del role
    stale = _setting("model.provider") or model_provider()
    if stale and stale.strip().lower() not in ("", "codex"):
        log.warning("ignoring stale provider override %r — bott is codex-only", stale)
    return "codex"


def _review_anti_affinity(model_id: str, provider: str = "codex") -> str:
    """DEPRECATED no-op. Anti-affinity (forcing review ≠ build) was removed on purpose:
    it only guards PRs bott ITSELF authored (rare), and to enforce it the reviewer was
    pushed off the strongest model onto a weaker one — which made the review bot miss real
    SQL/command injection (caught by the eval: gpt-5.4 called it a suggestion, gpt-5.5
    called it merge-blocking). The reviewer now runs on the same top model as build.
    Kept as an identity function so external call sites don't break."""
    del provider
    return model_id


def build_model(role: str = "chat", **overrides):
    """Build the model for a task role. Codex-only: always CodexExecChat, which shells to
    `codex exec` (text-only to Agno — chat tools ride bott's MCP server, not Agno
    tool-calling; build/review/triage call codex_cli.run_codex_exec directly and never
    come through here). `overrides` (e.g. retries) are forwarded to the model. _COMMON
    (retries + exponential backoff) applies so a transient provider 5xx is retried, not
    surfaced to the user as "error, try again later"."""
    resolve_provider(role)  # logs if a stale non-codex override is still configured
    model_id = resolve_model_id(role)
    from bott.shared.codex_exec_model import CodexExecChat
    return CodexExecChat(id=model_id, **{**_COMMON, **overrides})
