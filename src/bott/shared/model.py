"""Single place the LLM is built — provider is configuration, work is routed by task type.

Provider: codex (org backend direct) | bedrock | openrouter (prod). Role: 'chat' (everyday) vs
'heavy' (implementation/review). Provider classes are lazy-imported so optional deps
(boto3 for Bedrock) aren't required unless that provider is selected."""

from __future__ import annotations

from bott.shared.codex_tokens import get_valid_token  # module-level so tests can patch it

from .config import (
    model_provider,
    openrouter_api_key,
    role_model_id,
)

_COMMON = {"retries": 3, "exponential_backoff": True}


def _setting(key: str):
    """Admin override from the Postgres settings store; None if unset/unavailable."""
    try:
        from bott.shared.persistence.records import get_setting
        return get_setting(key)
    except Exception:  # noqa: BLE001 — settings store optional at construction time
        return None


def build_model(role: str = "chat", **overrides):
    """Build the model for a task role under the configured provider.
    `overrides` (e.g. retries, temperature) are forwarded to the underlying model."""
    provider = _setting("model.provider") or model_provider()
    model_id = _setting(f"model.{role}") or role_model_id(role)

    if provider == "codex":
        from bott.shared.codex_model import make_codex_model
        tok = get_valid_token()                      # model.get_valid_token — preserves test/conftest patch-point
        return make_codex_model(model_id, tok.access_token, tok.account_id, **overrides)
    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter
        return OpenRouter(id=model_id, api_key=openrouter_api_key(), **{**_COMMON, **overrides})
    if provider == "bedrock":
        from agno.models.aws import AwsBedrock
        return AwsBedrock(id=model_id, **overrides)
    raise ValueError(f"Unknown MODEL_PROVIDER '{provider}' (use codex|bedrock|openrouter).")
