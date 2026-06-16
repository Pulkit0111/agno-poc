"""Single place that constructs the LLM, so provider/auth isn't hardcoded.

The caller passes the endpoint (`base_url`) and `api_key` for its role, so different roles
can use different providers — e.g. the reviewer on a Codex-subscription proxy while the
manager runs a cheap/fast model on the OpenAI API. With no `base_url` it talks to OpenAI
(`api.openai.com`); any OpenAI-compatible endpoint (Azure, OpenRouter, a local model, or a
Codex proxy) works too.
"""

from __future__ import annotations

from agno.models.openai import OpenAIChat

from .config import DEFAULT_MODEL


def build_model(
    model_id: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    **overrides,
) -> OpenAIChat:
    """Construct a chat model for a given role. `base_url`/`api_key` come from the caller's
    role config; `overrides` win over the defaults (e.g. the reviewer bumps retries)."""
    opts: dict = {"id": model_id or DEFAULT_MODEL, "retries": 3, "exponential_backoff": True}
    if base_url:
        opts["base_url"] = base_url
    if api_key:
        opts["api_key"] = api_key
    elif base_url:
        # A custom endpoint that carries its own auth (local proxy) still needs the SDK to
        # send *something*; the value is ignored by such proxies.
        opts["api_key"] = "sk-local-endpoint-no-key-required"
    opts.update(overrides)
    return OpenAIChat(**opts)
