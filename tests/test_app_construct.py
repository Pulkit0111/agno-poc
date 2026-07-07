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


def test_readyz_reports_ok_when_db_reachable_and_no_worker_started(monkeypatch):
    """Regression guard for AgentOS's own /health always saying "ok" regardless of DB or
    worker state — /readyz must actually check the database. worker_thread_ref is None
    outside main(), so the worker-liveness check is skipped rather than false-failing."""
    from fastapi.testclient import TestClient

    from bott.interfaces import app
    client = TestClient(app.app)
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["problems"] == []


def test_readyz_reports_not_ready_when_worker_thread_died(monkeypatch):
    import threading

    from fastapi.testclient import TestClient

    from bott.interfaces import app

    dead_thread = threading.Thread(target=lambda: None)
    dead_thread.start()
    dead_thread.join()  # already finished — is_alive() is False
    monkeypatch.setattr(app, "_worker_thread_ref", dead_thread)

    client = TestClient(app.app)
    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert any("worker" in p for p in body["problems"])


def test_readyz_reports_not_ready_when_db_unreachable(monkeypatch):
    from fastapi.testclient import TestClient

    from bott.interfaces import app

    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("bott.shared.db.get_engine", boom)
    client = TestClient(app.app)
    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert any("database unreachable" in p for p in body["problems"])


def test_readyz_warns_but_stays_ready_when_codex_disconnected(monkeypatch):
    """Codex being disconnected must NOT flip readiness — restarting the process wouldn't
    fix a broken login, so treating this as "not ready" would just crash-loop uselessly."""
    from fastapi.testclient import TestClient

    from bott.interfaces import app
    from bott.shared import codex_tokens

    monkeypatch.setattr(app, "_model_provider", lambda: "codex")
    monkeypatch.setattr(codex_tokens, "is_connected", lambda: False)
    client = TestClient(app.app)
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert any("codex not connected" in w for w in body["warnings"])


def test_importing_app_configures_logging():
    """Regression guard: app.py must call setup_logging() at import time.

    Without this, the root logger has no handler, every bott.* INFO log is
    silently dropped, and the secret-redaction filter never runs on WARNING/
    ERROR records either. `bott.interfaces.app` is imported (directly or
    transitively) by every test in this suite, so by the time this test runs
    the root logger must already carry the configured handler + filter.
    """
    import logging

    import bott.interfaces.app  # noqa: F401 — import side effect is what's under test

    root = logging.getLogger()
    assert root.handlers, "root logger has no handler — setup_logging() was never called"
    filter_types = {type(f).__name__ for h in root.handlers for f in h.filters}
    assert "_RedactFilter" in filter_types, "secret-redaction filter is not attached"
