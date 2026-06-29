import pytest

from bott.shared.model import build_model


def test_codex_provider_uses_proxy_base_url(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    m = build_model("chat")
    assert m.id == "gpt-5.5"
    assert "127.0.0.1" in (m.base_url or "")


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
