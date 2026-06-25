"""One agent, one model. BOTT_MODEL is the single source of truth (default gpt-5.5); the old
manager/review split and the store-setting override no longer affect model selection."""

from bott.agents import bott_agent
from bott.shared import config


def test_bott_model_defaults_to_gpt_5_5(monkeypatch):
    monkeypatch.delenv("BOTT_MODEL", raising=False)
    monkeypatch.delenv("MANAGER_MODEL", raising=False)
    monkeypatch.delenv("REVIEW_MODEL", raising=False)
    assert config.bott_model() == "gpt-5.5"


def test_bott_model_honors_env(monkeypatch):
    monkeypatch.setenv("BOTT_MODEL", "gpt-5.4")
    assert config.bott_model() == "gpt-5.4"


def test_chat_model_is_bott_model_no_store_override(monkeypatch):
    """The bug we hit: a stale manager_model store setting silently pinned the model. The
    chat model now comes straight from BOTT_MODEL — effective_manager_model() reads no store
    setting at all, so a stale override is structurally impossible."""
    monkeypatch.setenv("BOTT_MODEL", "gpt-5.5")
    assert bott_agent.effective_manager_model() == "gpt-5.5"
