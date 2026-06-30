"""Direct in-process adapter to the org Codex backend (Responses API) using the managed
org token. Replaces the per-box npx proxy."""

from __future__ import annotations

from bott.shared import config
from bott.shared.codex_tokens import get_valid_token


def build_codex_model(model_id: str, **overrides):
    """An Agno model pointed at the org Codex backend with a fresh org token + account header.
    Raises CodexNotConnected (from get_valid_token) if the org account isn't connected."""
    from agno.models.openai import OpenAIResponses

    tok = get_valid_token()
    return OpenAIResponses(
        id=model_id,
        base_url=config.codex_backend_base_url(),
        api_key=tok.access_token,
        default_headers={"ChatGPT-Account-ID": tok.account_id},
        **overrides,
    )
