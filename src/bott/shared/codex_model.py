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

        # The ChatGPT/Codex backend REQUIRES the Responses API to stream ("Stream must be set
        # to true") — the parent's non-streaming invoke()/ainvoke() send stream=false and 400.
        # We stream on the wire, capture the terminal `response.completed` event's full
        # Response, and hand it to the parent's own parser — so callers still get one
        # aggregated ModelResponse (Slack UX unchanged, no incremental edits).
        def _stream_kwargs(self, messages, response_format, tools, tool_choice, compress_tool_results):
            params = self.get_request_params(
                messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
            )
            params.pop("background", None)  # background mode is invalid with streaming
            return {
                "model": self.id,
                "input": self._format_messages(messages, compress_tool_results, tools=tools),
                "stream": True,
                **params,
            }

        # The Codex backend delivers text/tool-calls as stream events and leaves the terminal
        # `response.completed` payload empty — so we accumulate the deltas through Agno's own
        # delta parser (`_parse_provider_response_delta`) and merge them into one ModelResponse.
        def _merge_delta(self, final, delta):
            if delta.content:
                final.content = (final.content or "") + delta.content
            if getattr(delta, "reasoning_content", None):
                final.reasoning_content = (final.reasoning_content or "") + delta.reasoning_content
            if delta.tool_calls:
                final.tool_calls = (final.tool_calls or []) + list(delta.tool_calls)
            if getattr(delta, "citations", None):
                final.citations = delta.citations
            if getattr(delta, "provider_data", None):
                final.provider_data = {**(final.provider_data or {}), **delta.provider_data}
            if getattr(delta, "extra", None):
                final.extra = final.extra or {}
                for k, v in delta.extra.items():
                    if isinstance(v, list):
                        final.extra.setdefault(k, []).extend(v)
                    else:
                        final.extra[k] = v

        def invoke(self, messages, assistant_message, response_format=None, tools=None,
                   tool_choice=None, run_response=None, compress_tool_results=False):  # type: ignore[override]
            from agno.exceptions import ModelProviderError
            from agno.models.response import ModelResponse
            assistant_message.metrics.start_timer()
            final = ModelResponse(content="")
            tool_use: dict = {}
            try:
                for event in self.get_client().responses.create(
                    **self._stream_kwargs(messages, response_format, tools, tool_choice, compress_tool_results)
                ):
                    delta, tool_use = self._parse_provider_response_delta(event, assistant_message, tool_use)
                    self._merge_delta(final, delta)
            except Exception as exc:  # noqa: BLE001 — surface as Agno's provider error
                raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc
            finally:
                assistant_message.metrics.stop_timer()
            return final

        async def ainvoke(self, messages, assistant_message, response_format=None, tools=None,
                          tool_choice=None, run_response=None, compress_tool_results=False):  # type: ignore[override]
            from agno.exceptions import ModelProviderError
            from agno.models.response import ModelResponse
            assistant_message.metrics.start_timer()
            final = ModelResponse(content="")
            tool_use: dict = {}
            try:
                stream = await self.get_async_client().responses.create(
                    **self._stream_kwargs(messages, response_format, tools, tool_choice, compress_tool_results)
                )
                async for event in stream:
                    delta, tool_use = self._parse_provider_response_delta(event, assistant_message, tool_use)
                    self._merge_delta(final, delta)
            except Exception as exc:  # noqa: BLE001
                raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc
            finally:
                assistant_message.metrics.stop_timer()
            return final

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
    # The ChatGPT/Codex backend rejects the Responses API `store=true` ("Store must be set
    # to false"); it does not persist responses. Force it off (callers may still override).
    overrides.setdefault("store", False)
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
