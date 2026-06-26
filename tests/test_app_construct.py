"""The consolidated Bott app constructs (agent + AgentOS + scheduler routes)."""

from __future__ import annotations


def test_github_tools_present_with_token(monkeypatch):
    """Agent exposes a GithubTools instance (and thus PR/commit read tools) when a token is set."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    import importlib

    from bott.agents import bott_agent
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
    """Agent constructs safely with no GitHub token — GithubTools must not be added.

    Also stub the `gh` CLI fallback so this holds on machines where `gh` is logged in
    (otherwise github_token() resolves a real token and GithubTools would be present).
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BOTT_POC_GITHUB_TOKEN", raising=False)
    from bott.shared import config
    monkeypatch.setattr(config, "_gh_cli_token", lambda: None)
    import importlib

    from bott.agents import bott_agent
    importlib.reload(bott_agent)
    a = bott_agent.build_bott_agent()
    from agno.tools.github import GithubTools
    github_toolkits = [t for t in (a.tools or []) if isinstance(t, GithubTools)]
    assert not github_toolkits, "GithubTools must NOT be added when no token is configured"


def test_skill_instructions_balanced_selection():
    """Forcing on a MATCH (so saved skills get reused), but anti-force-fit when none matches."""
    from bott.agents.bott_agent import SKILL_INSTRUCTIONS

    combined = " ".join(SKILL_INSTRUCTIONS)
    assert "MUST load" in combined, "must force loading a MATCHING skill (so saved skills get reused)"
    assert "near-miss" in combined, "must keep the anti-force-fit clause for non-matching tasks"


def test_agent_retains_more_history():
    from bott.agents.bott_agent import build_bott_agent
    a = build_bott_agent()
    assert (a.num_history_runs or 0) >= 15


def test_agent_constructs_without_connector_creds(monkeypatch):
    """build_bott_agent() must construct safely when no connector creds are present."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BOTT_POC_GITHUB_TOKEN", raising=False)
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.jira_read as jr
    from bott.shared import config as shared_config
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.setattr(shared_config, "_gh_cli_token", lambda: None)
    import importlib

    from bott.agents import bott_agent
    importlib.reload(bott_agent)
    a = bott_agent.build_bott_agent()
    assert a.id == "bott"


def test_app_constructs(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from bott.interfaces import app

    assert app._agent.id == "bott"
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/health" in paths
    assert any("schedule" in p for p in paths)  # scheduler mounted
