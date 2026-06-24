"""The consolidated Bott app constructs (agent + AgentOS + scheduler routes)."""

from __future__ import annotations


def test_agent_retains_more_history():
    from bott.agents.bott_agent import build_bott_agent
    a = build_bott_agent()
    assert (a.num_history_runs or 0) >= 15


def test_app_constructs(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from bott.interfaces import app

    assert app._agent.id == "bott"
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/health" in paths
    assert any("schedule" in p for p in paths)  # scheduler mounted
