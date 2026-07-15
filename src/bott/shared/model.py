"""Single place the LLM is built — provider is configuration, work is routed by task type.

Provider: codex (org backend direct) | bedrock | openrouter (prod). Role: 'chat' (everyday) vs
'heavy' (implementation/review). Provider classes are lazy-imported so optional deps
(boto3 for Bedrock) aren't required unless that provider is selected."""

from __future__ import annotations

from bott.shared.observability.logging_setup import get_logger

from .config import (
    model_provider,
    model_retry_delay_s,
    openrouter_api_key,
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


def resolve_model_id(role: str) -> str:
    """The model id a role resolves to right now (admin settings-store override → env
    fallback chain). build/review also honor a legacy `model.heavy` store override."""
    direct = _setting(f"model.{role}")
    if direct:
        return direct
    if role in ("build", "review"):
        legacy = _setting("model.heavy")
        if legacy:
            return legacy
    return role_model_id(role)


def resolve_provider(role: str) -> str:
    """The provider a role resolves to right now: per-role settings-store override
    (`model.provider.<role>`) → global settings-store override (`model.provider`) →
    env default (`config.model_provider()`). Lets an admin put e.g. Chat on OpenRouter
    while Build/Review stay on Codex. Whitespace-only settings values are treated as
    absent (a stray space shouldn't silently pin a provider)."""
    per_role = _setting(f"model.provider.{role}")
    if per_role and per_role.strip():
        return per_role.strip()
    global_override = _setting("model.provider")
    if global_override and global_override.strip():
        return global_override.strip()
    return model_provider()


def _review_anti_affinity(model_id: str, provider: str) -> str:
    """The reviewer must not be the model that wrote the code. If the review role resolves
    to the SAME id as the build role, swap to an alternate so implement and review never
    share weights (same blind spots while writing = same blind spots while reviewing).
    Best-effort per provider: codex picks the first different catalog model; other providers
    keep the id but log loudly (the admin should set model.review explicitly)."""
    build_id = resolve_model_id("build")
    if model_id != build_id:
        return model_id
    if provider == "codex":
        from .config import FALLBACK_CODEX_MODELS
        # Skip '-codex'-suffixed ids: the ChatGPT-account backend rejects them ("model is
        # not supported when using Codex with a ChatGPT account") — swapping onto one would
        # break every review, which is worse than the bias we're avoiding.
        for alt in FALLBACK_CODEX_MODELS:
            if alt != build_id and not alt.endswith("-codex"):
                log.warning("review model == build model (%s) — swapping review to %s "
                            "(anti-affinity)", build_id, alt)
                return alt
    log.warning("review model == build model (%s) and no safe alternate available for "
                "provider %s — keeping it (same-model review beats no review); set "
                "model.review to choose the reviewer explicitly.", build_id, provider)
    return model_id


def build_model(role: str = "chat", **overrides):
    """Build the model for a task role under the configured provider.
    `overrides` (e.g. retries, temperature) are forwarded to the underlying model."""
    provider = resolve_provider(role)
    model_id = resolve_model_id(role)
    if role == "review":
        model_id = _review_anti_affinity(model_id, provider)

    # _COMMON (retries + exponential backoff) applies to EVERY provider: a transient provider
    # 5xx must be retried, not surfaced to the user as "error, try again later". Callers can
    # still override via `overrides`.
    if provider == "codex":
        # Everything runs through the official codex CLI now. CodexExecChat is text-only
        # (chat tools ride bott's MCP server, not Agno tool-calling) — build/review/triage
        # call codex_cli.run_codex_exec directly and never come through here.
        from bott.shared.codex_exec_model import CodexExecChat
        return CodexExecChat(id=model_id, **{**_COMMON, **overrides})
    return _build_for_provider(provider, model_id, overrides)


def _build_for_provider(provider: str, model_id: str, overrides: dict):
    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter
        # Many OpenRouter models emit chain-of-thought as `reasoning_content`, which the Agno
        # Slack interface renders as a "*Reasoning:*" block before the answer (event_handler.py).
        # Users should see the reply, not the raw thinking — ask OpenRouter to still reason but
        # NOT return the reasoning tokens (`reasoning.exclude`), so reasoning_content stays empty.
        # A caller can override via `overrides["extra_body"]`.
        return OpenRouter(
            id=model_id,
            api_key=openrouter_api_key(),
            **{"extra_body": {"reasoning": {"exclude": True}}, **_COMMON, **overrides},
        )
    if provider == "bedrock":
        from agno.models.aws import AwsBedrock
        return AwsBedrock(id=model_id, **{**_COMMON, **overrides})
    raise ValueError(f"Unknown MODEL_PROVIDER '{provider}' (use codex|bedrock|openrouter).")
