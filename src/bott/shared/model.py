"""Single place the LLM is built — provider is configuration, work is routed by task type.

Provider: codex (dev proxy) | bedrock | openrouter (prod). Role: 'chat' (everyday) vs
'heavy' (implementation/review). Provider classes are lazy-imported so optional deps
(boto3 for Bedrock) aren't required unless that provider is selected."""

from __future__ import annotations

from .config import (
    _codex_proxy_base_url,
    model_provider,
    openrouter_api_key,
    role_model_id,
)

_COMMON = {"retries": 3, "exponential_backoff": True}


def build_model(role: str = "chat", **overrides):
    """Build the model for a task role under the configured provider.
    `overrides` (e.g. retries, temperature) are forwarded to the underlying model."""
    provider = model_provider()
    model_id = role_model_id(role)

    if provider == "codex":
        from agno.models.openai import OpenAIChat
        return OpenAIChat(
            id=model_id,
            base_url=_codex_proxy_base_url(),
            api_key="sk-local-endpoint-no-key-required",
            **{**_COMMON, **overrides},
        )
    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter
        return OpenRouter(id=model_id, api_key=openrouter_api_key(), **{**_COMMON, **overrides})
    if provider == "bedrock":
        from agno.models.aws import AwsBedrock
        return AwsBedrock(id=model_id, **overrides)
    raise ValueError(f"Unknown MODEL_PROVIDER '{provider}' (use codex|bedrock|openrouter).")
