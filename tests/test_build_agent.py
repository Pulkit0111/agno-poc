import pytest

from bott.agents.bott_agent import MEMORY_CAPTURE_INSTRUCTIONS, build_agent
from bott.shared.identity import IsolationError


def test_build_agent_requires_user_id():
    with pytest.raises(IsolationError):
        build_agent("", db=None)


def test_build_agent_returns_agent_with_tools():
    agent = build_agent("alice@axelerant.com", db=None)
    assert agent.name == "Bott"
    assert agent.tools  # toolset attached


def test_memory_is_deterministic_not_discretionary():
    """Regression: name/location stated in one Slack thread must survive into the next.

    The bug (2026-07-15, #bott-testing) was discretionary agentic memory silently dropping a
    plain declarative ("I live in Srinagar") while still replying "I've noted that". Guard the
    fix: capture runs after every turn (update_memory_on_run) via a scoped memory manager, and
    the old agentic path is OFF. update_memory_on_run and enable_agentic_memory are mutually
    exclusive in Agno — if agentic is re-enabled it silently wins and this bug returns."""
    agent = build_agent("alice@axelerant.com", db=None)

    assert agent.update_memory_on_run is True
    assert not getattr(agent, "enable_agentic_memory", False)
    assert agent.memory_manager is not None
    # Recall must stay automatic: stored memories injected into context each run.
    assert agent.add_memories_to_context is True


def test_memory_capture_scope_keeps_durable_facts_drops_chatter():
    """The capture policy must keep identity/location/preferences (a plain declarative counts)
    and explicitly exclude transient task chatter."""
    text = MEMORY_CAPTURE_INSTRUCTIONS.lower()
    for durable in ("name", "location", "role", "preferences", "declarative"):
        assert durable in text, f"capture policy should mention {durable!r}"
    assert "do not capture" in text
    assert "transient" in text
