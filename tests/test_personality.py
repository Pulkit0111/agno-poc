"""Presence tests for bott.agents.personality — voice / tone guardrails, plus
get_identity()/get_voice() versioned-prompt fallback tests."""

import time

import pytest

from bott.agents.personality import VOICE


def test_voice_has_grounded_answer_guidance():
    """VOICE must explicitly call out 'Best read:' as an anti-pattern and
    frame the expected behaviour in teammate terms."""
    assert "Best read:" in VOICE, "VOICE should name 'Best read:' as something NOT to do"
    assert "teammate" in VOICE.lower(), "VOICE should frame grounded answers as a teammate would speak"


def test_voice_has_single_natural_question_instruction():
    """VOICE must instruct Bott to ask one short, natural question (not a menu)."""
    assert "ask ONE short" in VOICE, (
        "VOICE should instruct Bott to ask ONE short natural question, not a menu of options"
    )


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    import os

    from bott.shared import db
    from bott.shared.schema import init_schema
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "agentos.db"))
    db.get_engine(fresh=True)
    init_schema()


def test_get_identity_falls_back_to_constant():
    from bott.agents import personality
    assert personality.get_identity() == personality.IDENTITY


def test_get_identity_uses_latest_saved_version():
    from bott.agents import personality
    from bott.shared.persistence import prompts_store
    prompts_store.save_version("identity", "custom identity", "note", "a@x.com", time.time())
    assert personality.get_identity() == "custom identity"


def test_get_voice_falls_back_to_constant():
    from bott.agents import personality
    assert personality.get_voice() == personality.VOICE


def test_get_voice_uses_latest_saved_version():
    from bott.agents import personality
    from bott.shared.persistence import prompts_store
    prompts_store.save_version("voice", "custom voice", "note", "a@x.com", time.time())
    assert personality.get_voice() == "custom voice"
