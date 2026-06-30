import pytest

from bott.shared import model as model_mod
from bott.shared.model import build_model


def test_codex_provider_uses_direct_backend(monkeypatch):
    """Codex provider now uses the direct org backend (not the npx proxy)."""
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok-abc", "acc-1"))
    m = build_model("chat")
    assert m.id == "gpt-5.5"
    assert "backend-api/codex" in (m.base_url or "")


def test_openrouter_provider(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("BOTT_HEAVY_MODEL", "anthropic/claude-sonnet-4")
    m = build_model("heavy")
    assert m.id == "anthropic/claude-sonnet-4"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "nope")
    with pytest.raises(ValueError):
        build_model("chat")


def test_codex_provider_builds_adapter(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok-abc", "acc-1"))
    m = model_mod.build_model("chat")
    assert m.id == "gpt-5.5"
    assert "backend-api/codex" in (m.base_url or "")


def test_codex_not_connected_propagates(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    from bott.shared import codex_tokens as ct
    def boom(): raise ct.CodexNotConnected("nope")
    monkeypatch.setattr(model_mod, "get_valid_token", boom)
    with pytest.raises(ct.CodexNotConnected):
        model_mod.build_model("chat")


def test_settings_override_beats_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setattr(model_mod, "_setting", lambda k: {"model.provider": "openrouter"}.get(k))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "x/y")
    m = model_mod.build_model("chat")
    assert m.id == "x/y"  # OpenRouter model built because settings overrode provider
