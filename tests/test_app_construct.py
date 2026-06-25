"""The consolidated Bott app constructs (agent + AgentOS + scheduler routes)."""

from __future__ import annotations


def test_github_tools_present_with_token(monkeypatch):
    """Agent exposes a GithubTools instance (and thus PR/commit read tools) when a token is set."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    from bott.agents import bott_agent
    import importlib
    importlib.reload(bott_agent)
    a = bott_agent.build_bott_agent()
    from agno.tools.github import GithubTools
    github_toolkits = [t for t in (a.tools or []) if isinstance(t, GithubTools)]
    assert github_toolkits, "Expected a GithubTools instance in agent.tools when GITHUB_TOKEN is set"

    # Allowlist enforcement: a known write tool must be absent; a known read tool must be present.
    gh = github_toolkits[0]
    assert "create_pull_request" not in gh.functions, (
        "create_pull_request (write) must NOT be exposed — GithubTools is allowlist-only"
    )
    assert "get_pull_request" in gh.functions, (
        "get_pull_request (read) must be exposed via the allowlist"
    )


def test_github_tools_absent_without_token(monkeypatch):
    """Agent constructs safely with no GitHub token — GithubTools must not be added."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BOTT_POC_GITHUB_TOKEN", raising=False)
    from bott.agents import bott_agent
    import importlib
    importlib.reload(bott_agent)
    a = bott_agent.build_bott_agent()
    from agno.tools.github import GithubTools
    github_toolkits = [t for t in (a.tools or []) if isinstance(t, GithubTools)]
    assert not github_toolkits, "GithubTools must NOT be added when no token is configured"


def test_skill_instructions_no_must_load():
    from bott.agents.bott_agent import SKILL_INSTRUCTIONS

    combined = " ".join(SKILL_INSTRUCTIONS)
    assert "MUST load" not in combined, (
        "SKILL_INSTRUCTIONS must not contain 'MUST load' — use balanced skill-selection wording"
    )


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
