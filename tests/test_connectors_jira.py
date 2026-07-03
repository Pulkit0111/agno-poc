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


def test_get_jira_issue_returns_rich_detail(monkeypatch):
    monkeypatch.setattr(jira_read.config, "jira_configured", lambda: True)
    raw = {"key": "IRM-515", "fields": {
        "summary": "Registration revamp - issues",
        "status": {"name": "Merge to QA", "statusCategory": {"key": "indeterminate"}},
        "issuetype": {"name": "Bug"},
        "assignee": {"displayName": "Asha Dev"},
        "priority": {"name": "High"},
        "description": {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Users cannot register."}]}]},
    }}
    monkeypatch.setattr(jira_read, "_client", lambda: _client(monkeypatch, raw))
    out = jira_read.get_jira_issue("IRM-515")
    # The previous behavior returned only key/summary/status; detail must now surface more.
    assert "Asha Dev" in out and "High" in out and "Users cannot register." in out
