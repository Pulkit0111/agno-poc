"""Direct in-process adapter to the org Codex backend (Responses API) using the managed
org token. Replaces the per-box npx proxy.

CodexModel subclasses OpenAIResponses and re-resolves the Codex access token on every
client access, so a long-lived model instance (e.g. the shared chat agent in app.py) never
gets stuck using an expired token — the client is rebuilt whenever the token rotates."""

from __future__ import annotations

from bott.shared import config
from bott.shared.codex_tokens import get_valid_token


def _make_codex_model_class():
    """Lazily import OpenAIResponses and return the CodexModel subclass."""
    from agno.models.openai import OpenAIResponses

    class CodexModel(OpenAIResponses):
        """OpenAIResponses subclass that re-resolves the Codex access token per request.

        On each call to get_client/get_async_client, the current valid token is fetched
        (from DB/cache via get_valid_token).  If the token string has changed since the
        last call, the cached OpenAI client is invalidated so the parent rebuilds it with
        the fresh api_key and account-ID header.  This ensures a process-lifetime model
        instance never holds a stale, expired access token.
        """

        def __init__(self, **kw):
            super().__init__(**kw)
            # Track the last access token used to seed the cached client.
            self._last_token_str: str = kw.get("api_key", "") or ""

        def _refresh_if_rotated(self) -> None:
            """Re-resolve the token; invalidate the cached client if it rotated."""
            tok = get_valid_token()
            if tok.access_token != self._last_token_str:
                # Token has rotated — update model fields and bust the cached clients.
                self.api_key = tok.access_token
                self.default_headers = {"ChatGPT-Account-ID": tok.account_id}
                self.client = None
                self.async_client = None
                self._last_token_str = tok.access_token

        def get_client(self):  # type: ignore[override]
            self._refresh_if_rotated()
            return super().get_client()

        def get_async_client(self):  # type: ignore[override]
            self._refresh_if_rotated()
            return super().get_async_client()

    return CodexModel


# Module-level cache: built once per process on first import of build_codex_model.
_CodexModel = None


def _get_codex_model_class():
    global _CodexModel  # noqa: PLW0603
    if _CodexModel is None:
        _CodexModel = _make_codex_model_class()
    return _CodexModel


def make_codex_model(model_id: str, access_token: str, account_id: str, **overrides):
    """Build a CodexModel seeded with an ALREADY-FETCHED token.

    The caller is responsible for obtaining the initial token. CodexModel's per-request
    refresh still calls get_valid_token() internally — this factory does NOT.
    This is the preferred low-level entry-point: callers control where the seed token
    comes from (enables test patch-points in higher-level modules)."""
    return _get_codex_model_class()(
        id=model_id,
        base_url=config.codex_backend_base_url(),
        api_key=access_token,
        default_headers={"ChatGPT-Account-ID": account_id},
        **overrides,
    )


def build_codex_model(model_id: str, **overrides):
    """An Agno model pointed at the org Codex backend with a fresh org token + account header.

    Returns a CodexModel that re-resolves the access token on every client access, so a
    long-lived agent never gets stuck on a stale token.

    Raises CodexNotConnected (from get_valid_token) if the org account isn't connected."""
    tok = get_valid_token()
    return make_codex_model(model_id, tok.access_token, tok.account_id, **overrides)
