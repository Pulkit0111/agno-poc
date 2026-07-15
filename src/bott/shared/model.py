"""Single place the LLM is built — codex-only: every role runs on the org ChatGPT
subscription through the official codex CLI (CodexExecChat / codex_cli.run_codex_exec).

Roles: 'chat' (everyday) vs 'build'/'review' ('heavy' legacy tier as fallback). The
per-role PROVIDER switching layer (OpenRouter/Bedrock) is gone; per-role MODEL IDS
remain (resolve_model_id + review anti-affinity)."""

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
    """The reviewer must not be the model that wrote the code. If the review role resolves
    to the SAME id as the build role, swap to the first different codex catalog model so
    implement and review never share weights (same blind spots while writing = same blind
    spots while reviewing)."""
    del provider  # codex-only; kept for caller compat
    build_id = resolve_model_id("build")
    if model_id != build_id:
        return model_id
    from .config import FALLBACK_CODEX_MODELS
    # Skip '-codex'-suffixed ids: the ChatGPT-account backend rejects them ("model is
    # not supported when using Codex with a ChatGPT account") — swapping onto one would
    # break every review, which is worse than the bias we're avoiding.
    for alt in FALLBACK_CODEX_MODELS:
        if alt != build_id and not alt.endswith("-codex"):
            log.warning("review model == build model (%s) — swapping review to %s "
                        "(anti-affinity)", build_id, alt)
            return alt
    log.warning("review model == build model (%s) and no safe alternate available — "
                "keeping it (same-model review beats no review); set model.review to "
                "choose the reviewer explicitly.", build_id)
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
    if role == "review":
        model_id = _review_anti_affinity(model_id)

    from bott.shared.codex_exec_model import CodexExecChat
    return CodexExecChat(id=model_id, **{**_COMMON, **overrides})
