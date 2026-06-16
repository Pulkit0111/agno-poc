"""Single place that constructs the LLM, so provider/auth isn't hardcoded.

By default this is OpenAI (`api.openai.com`) authenticated with an API key. Set
`REVIEW_MODEL_BASE_URL` to point at any OpenAI-compatible endpoint instead — Azure
OpenAI, OpenRouter, a self-hosted gateway, a local model (Ollama/LM Studio), or a local
proxy that carries a ChatGPT/Codex *subscription* token (so no API key is needed). The
rest of the app calls `build_model()` and is agnostic to which of these is in play.
"""

from __future__ import annotations

from agno.models.openai import OpenAIChat

from .config import DEFAULT_MODEL, model_api_key, model_base_url


def build_model(model_id: str | None = None, **overrides) -> OpenAIChat:
    """Build the chat model from config. `overrides` win over the defaults (e.g. the
    review runner bumps retries). Works against OpenAI or any OpenAI-compatible base_url."""
    opts: dict = {"id": model_id or DEFAULT_MODEL, "retries": 3, "exponential_backoff": True}

    base_url = model_base_url()
    if base_url:
        opts["base_url"] = base_url

    api_key = model_api_key()
    if api_key:
        opts["api_key"] = api_key
    elif base_url:
        # A custom endpoint that carries its own auth (local proxy) still needs the SDK
        # to send *something*; the value is ignored by such proxies.
        opts["api_key"] = "sk-local-endpoint-no-key-required"

    opts.update(overrides)
    return OpenAIChat(**opts)
