"""Aggregator connector_tools() — gates all off; includes slack when token present."""

from bott.skills import connectors


def test_aggregator_gates_all_off(monkeypatch):
    import bott.skills.connectors.jira_read as jr
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.slack_read as sr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    assert connectors.connector_tools() == []


def test_aggregator_includes_slack_when_token_present(monkeypatch):
    import bott.skills.connectors.jira_read as jr
    import bott.skills.connectors.confluence_read as cr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    names = {getattr(t, "__name__", "") for t in connectors.connector_tools()}
    assert "read_slack_thread" in names
