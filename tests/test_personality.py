"""Presence tests for bott.agents.personality — voice / tone guardrails."""

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
