import importlib

from bott.shared import config


def test_model_provider_defaults_to_codex(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    assert config.model_provider() == "codex"


def test_model_provider_normalizes(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "  OpenRouter ")
    assert config.model_provider() == "openrouter"


def test_role_model_id_chat_and_heavy(monkeypatch):
    monkeypatch.setenv("BOTT_CHAT_MODEL", "fast-1")
    monkeypatch.setenv("BOTT_HEAVY_MODEL", "strong-1")
    assert config.role_model_id("chat") == "fast-1"
    assert config.role_model_id("heavy") == "strong-1"


def test_role_model_id_unknown_role_falls_back_to_chat(monkeypatch):
    monkeypatch.setenv("BOTT_CHAT_MODEL", "fast-1")
    assert config.role_model_id("nonsense") == "fast-1"
