import pytest

from bott.agents.bott_agent import build_agent
from bott.shared.identity import IsolationError


def test_build_agent_requires_user_id():
    with pytest.raises(IsolationError):
        build_agent("", db=None)


def test_build_agent_returns_agent_with_tools():
    agent = build_agent("alice@axelerant.com", db=None)
    assert agent.name == "Bott"
    assert agent.tools  # toolset attached
