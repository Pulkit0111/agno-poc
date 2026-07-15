"""Codex-only provider resolution — the per-role provider switching layer is gone."""
from __future__ import annotations

from bott.shared import model as model_mod


def test_resolve_provider_is_always_codex(monkeypatch):
    monkeypatch.setattr(model_mod, "_setting", lambda k: None)
    for role in ("chat", "build", "review", "heavy"):
        assert model_mod.resolve_provider(role) == "codex"


def test_stale_store_override_is_ignored(monkeypatch):
    """Old deployments may still carry model.provider rows — they must be ignored (with a
    warning), never honored: bott is codex-only."""
    settings = {"model.provider.chat": "openrouter", "model.provider": "bedrock"}
    monkeypatch.setattr(model_mod, "_setting", lambda k: settings.get(k))
    assert model_mod.resolve_provider("chat") == "codex"
    m = model_mod.build_model("chat")
    assert type(m).__name__ == "CodexExecChat"


def test_stale_env_provider_is_ignored(monkeypatch):
    monkeypatch.setattr(model_mod, "_setting", lambda k: None)
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    assert model_mod.resolve_provider("chat") == "codex"
    assert type(model_mod.build_model("chat")).__name__ == "CodexExecChat"


def test_stale_openrouter_model_id_is_ignored(monkeypatch):
    """A leftover model.chat row with an OpenRouter-style id ('vendor/model') must be
    ignored — a ChatGPT-account codex login 400s on those, so honoring it would break
    every chat turn (observed live: 'poolside/laguna-m.1:free')."""
    monkeypatch.setattr(model_mod, "_setting",
                        lambda k: {"model.chat": "poolside/laguna-m.1:free"}.get(k))
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    assert model_mod.resolve_model_id("chat") == "gpt-5.5"
