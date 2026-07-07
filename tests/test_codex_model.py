"""Regression tests for CodexModel token re-resolution."""
from __future__ import annotations

import asyncio
import threading

import httpx

import bott.shared.codex_model as cm
from bott.shared.codex_tokens import CodexToken


def test_codex_model_reresolves_token_on_rotation(monkeypatch):
    """A long-lived CodexModel invalidates its cached client when the token rotates."""
    tokens = [CodexToken("tok-B", "acc")]
    # Patch the module-level get_valid_token so _refresh_if_rotated sees the new token.
    monkeypatch.setattr(cm, "get_valid_token", lambda: tokens.pop(0))
    # Seed with tok-A so the first refresh sees tok-B as a rotation.
    m = cm.make_codex_model("gpt-5.5", "tok-A", "acc")
    assert m._last_token_str == "tok-A"
    m.client = object()          # pretend sync + async clients are cached
    m.async_client = object()
    m._refresh_if_rotated()      # token rotates: get_valid_token returns tok-B
    assert m.api_key == "tok-B"          # api_key updated to the fresh token
    assert m.default_headers == {"ChatGPT-Account-ID": "acc"}  # account header refreshed
    assert m.client is None and m.async_client is None  # BOTH cached clients invalidated


def test_codex_model_no_invalidation_when_token_stable(monkeypatch):
    """When the token hasn't changed, the cached client is left intact."""
    monkeypatch.setattr(cm, "get_valid_token", lambda: CodexToken("tok-A", "acc"))
    m = cm.make_codex_model("gpt-5.5", "tok-A", "acc")
    sentinel = object()
    m.client = sentinel
    m._refresh_if_rotated()
    assert m.api_key == "tok-A"
    assert m.client is sentinel          # NOT invalidated — same token


def test_codex_model_clients_get_a_real_timeout(monkeypatch):
    """Regression: the client defaulted to timeout=None — a hung upstream stream hung
    forever while holding one of the org-wide concurrency slots (4 hung calls froze chat
    for the whole org)."""
    monkeypatch.delenv("CODEX_TIMEOUT_S", raising=False)
    m = cm.make_codex_model("gpt-5.5", "tok", "acc")
    t = m.timeout
    assert isinstance(t, httpx.Timeout)
    assert t.connect == 10.0             # connect fails fast
    assert t.read == 300.0               # generous default for long streamed responses
    # and it actually reaches the OpenAI client params (sync AND async share these)
    assert m._get_client_params()["timeout"] is t


def test_codex_timeout_env_override(monkeypatch):
    monkeypatch.setenv("CODEX_TIMEOUT_S", "77")
    m = cm.make_codex_model("gpt-5.5", "tok", "acc")
    assert m.timeout.read == 77.0
    assert m.timeout.connect == 10.0


def test_ainvoke_keeps_token_and_usage_io_off_the_event_loop(monkeypatch):
    """get_valid_token (DB read + Fernet decrypt; blocking HTTP refresh on rotation) and
    _record_usage (DB INSERT) are sync I/O — ainvoke must push them through
    asyncio.to_thread, never run them directly on the event loop, or one call's refresh
    freezes every concurrent user's chat."""
    from bott.shared import codex_concurrency
    codex_concurrency.reset_for_tests()  # async semaphores must bind to THIS test's loop

    token_threads: list[threading.Thread] = []
    usage_threads: list[threading.Thread] = []

    def fake_token():
        token_threads.append(threading.current_thread())
        return CodexToken("tok-A", "acc")

    monkeypatch.setattr(cm, "get_valid_token", fake_token)
    monkeypatch.setattr(cm, "_record_usage",
                        lambda *a: usage_threads.append(threading.current_thread()))

    m = cm.make_codex_model("gpt-5.5", "tok-A", "acc")

    class _Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _Responses:
        async def create(self, **kw):
            return _Stream()

    class _Client:
        responses = _Responses()

        def is_closed(self):
            return False

    m.async_client = _Client()
    m._stream_kwargs = lambda *a, **k: {}

    class _Metrics:
        def start_timer(self):
            pass

        def stop_timer(self):
            pass

    class _Msg:
        metrics = _Metrics()

    loop_thread = threading.current_thread()  # asyncio.run drives the loop on this thread
    asyncio.run(m.ainvoke([], _Msg()))
    assert token_threads and token_threads[0] is not loop_thread
    assert usage_threads and usage_threads[0] is not loop_thread
