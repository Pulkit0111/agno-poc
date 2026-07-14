"""Single place the LLM is built — provider is configuration, work is routed by task type.

Provider: codex (org backend direct) | bedrock | openrouter (prod). Role: 'chat' (everyday) vs
'heavy' (implementation/review). Provider classes are lazy-imported so optional deps
(boto3 for Bedrock) aren't required unless that provider is selected."""

from __future__ import annotations

from bott.shared.codex_tokens import (  # module-level so tests can patch
    CodexNotConnected,
    get_valid_token,
)
from bott.shared.observability.logging_setup import get_logger

from .config import (
    fallback_model_id,
    fallback_model_provider,
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
        return _build_codex_model(model_id, overrides)
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


def _build_codex_model(model_id: str, overrides: dict):
    """Build the codex-provider model. On a broken shared login (never connected, or refresh
    failed), this must NOT raise: build_model("chat") runs once at agent-construction time,
    at process/app import — a raised exception here used to crash the entire app (Slack AND
    the admin console) before an admin could ever reach the Connect-Codex button to fix it.
    Instead it alerts admins and returns a model seeded with placeholder credentials; Agno's
    CodexModel re-resolves a real token on every actual call (see codex_model.py's
    _refresh_if_rotated), so the app/console stay up and the model becomes usable the instant
    Codex is reconnected — no restart needed. Until then, an actual chat/build/review attempt
    fails per-request (Agno's own retry + error surfacing), which is a normal-looking error
    for one request instead of the whole bot being unreachable."""
    from bott.shared.codex_model import make_codex_model

    try:
        tok = get_valid_token()  # model.get_valid_token — preserves test/conftest patch-point
        return make_codex_model(model_id, tok.access_token, tok.account_id, **{**_COMMON, **overrides})
    except CodexNotConnected as e:
        from bott.shared.alerts import alert_admins_throttled

        fallback = fallback_model_provider()
        if fallback and fallback != "codex":
            alert_admins_throttled(
                "codex-disconnected",
                f"Bott's shared Codex (ChatGPT) login is broken ({e}) — falling back to "
                f"{fallback} until it's reconnected. Reconnect it from the console "
                "(Models page).",
            )
            log.error("codex unavailable (%s) — falling back to provider=%s", e, fallback)
            return _build_for_provider(fallback, fallback_model_id(fallback), overrides)

        alert_admins_throttled(
            "codex-disconnected",
            f"Bott's shared Codex (ChatGPT) login is broken: {e}. Every codex: model call "
            "will fail until an admin reconnects it from the console (Models page).",
        )
        log.error("codex unavailable at model-construction time (%s) — returning a model that "
                  "re-checks the connection on each actual use instead of failing to build at "
                  "all, so the app and console stay reachable to reconnect it.", e)
        return make_codex_model(model_id, "", "", **{**_COMMON, **overrides})
