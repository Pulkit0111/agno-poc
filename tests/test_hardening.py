"""Tests for the hardening pass: injection-guard presence + per-task model config."""

import bott.shared.config as config
from bott.agents.code_review.agent.prompt import PROMPT_VERSION, UNTRUSTED_GUARD


def test_prompt_version_bumped():
    assert PROMPT_VERSION == "v3.7-agno"


def test_untrusted_guard_has_key_directives():
    g = UNTRUSTED_GUARD.lower()
    assert "untrusted" in g
    assert "never instructions" in g or "do not obey" in g
    assert "prompt-injection" in g or "social-engineering" in g
    assert "begin untrusted pr content" in g


def test_manager_model_fallback_to_review_model(monkeypatch):
    monkeypatch.delenv("MANAGER_MODEL", raising=False)
    assert config.manager_model() == config.DEFAULT_MODEL


def test_bott_model_is_single_source(monkeypatch):
    # One agent, one model: BOTT_MODEL wins; the legacy MANAGER_MODEL does not override it.
    monkeypatch.setenv("BOTT_MODEL", "gpt-5.5")
    monkeypatch.setenv("MANAGER_MODEL", "fast-mini")
    assert config.bott_model() == "gpt-5.5"
    assert config.manager_model() == "gpt-5.5"  # deprecated alias resolves to bott_model()
