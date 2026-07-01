"""Regression tests for CodexModel token re-resolution."""
from __future__ import annotations

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
