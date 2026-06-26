from bott.shared.integrations.jira import JiraClient
from bott.skills.connectors import jira_read


def _client(monkeypatch, raw):
    c = JiraClient(base_url="https://x.atlassian.net", email="e@x.com", api_token="t")
    monkeypatch.setattr(c, "_get", lambda path, params=None: raw)
    return c


def test_search_issues_normalizes(monkeypatch):
    raw = {"issues": [{"key": "PADI-1", "fields": {"summary": "Fix login",
            "status": {"name": "Done", "statusCategory": {"key": "done"}},
            "issuetype": {"name": "Bug"}}}]}
    c = _client(monkeypatch, raw)
    out = c.search_issues("login")
    assert out and out[0]["key"] == "PADI-1" and out[0]["status"] == "Done"


def test_jira_search_tool_formats_and_gates(monkeypatch):
    monkeypatch.setattr(jira_read.config, "jira_configured", lambda: False)
    assert "isn't configured" in jira_read.jira_search("login").lower()
    assert jira_read.jira_read_tools() == []  # gated off when unconfigured
