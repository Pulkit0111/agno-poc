"""Single place the LLM is built — provider is configuration, work is routed by task type.

Provider: codex (org backend direct) | bedrock | openrouter (prod). Role: 'chat' (everyday) vs
'heavy' (implementation/review). Provider classes are lazy-imported so optional deps
(boto3 for Bedrock) aren't required unless that provider is selected."""

from __future__ import annotations

from bott.shared.codex_tokens import get_valid_token  # module-level so tests can patch it
from bott.shared.observability.logging_setup import get_logger

from .config import (
    model_provider,
    openrouter_api_key,
    role_model_id,
)

log = get_logger("bott.model")

_COMMON = {"retries": 3, "exponential_backoff": True}


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
    provider = _setting("model.provider") or model_provider()
    model_id = resolve_model_id(role)
    if role == "review":
        model_id = _review_anti_affinity(model_id, provider)

    # _COMMON (retries + exponential backoff) applies to EVERY provider: a transient provider
    # 5xx must be retried, not surfaced to the user as "error, try again later". Callers can
    # still override via `overrides`.
    if provider == "codex":
        from bott.shared.codex_model import make_codex_model
        tok = get_valid_token()                      # model.get_valid_token — preserves test/conftest patch-point
        return make_codex_model(model_id, tok.access_token, tok.account_id, **{**_COMMON, **overrides})
    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter
        return OpenRouter(id=model_id, api_key=openrouter_api_key(), **{**_COMMON, **overrides})
    if provider == "bedrock":
        from agno.models.aws import AwsBedrock
        return AwsBedrock(id=model_id, **{**_COMMON, **overrides})
    raise ValueError(f"Unknown MODEL_PROVIDER '{provider}' (use codex|bedrock|openrouter).")
