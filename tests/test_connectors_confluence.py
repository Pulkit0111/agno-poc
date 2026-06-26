from bott.shared import config
from bott.skills.connectors import confluence_read


def test_confluence_creds_derive_from_jira(monkeypatch):
    monkeypatch.delenv("CONFLUENCE_URL", raising=False)
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "e@acme.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    assert config.confluence_url() == "https://acme.atlassian.net/wiki"
    assert config.confluence_username() == "e@acme.com"
    assert config.confluence_api_key() == "tok"
    assert config.confluence_configured() is True


def test_confluence_tools_gated_off_when_unconfigured(monkeypatch):
    monkeypatch.setattr(confluence_read.config, "confluence_configured", lambda: False)
    assert confluence_read.confluence_read_tools() == []


def test_confluence_tools_are_read_only(monkeypatch):
    monkeypatch.setattr(confluence_read.config, "confluence_configured", lambda: True)
    monkeypatch.setattr(confluence_read.config, "confluence_url", lambda: "https://acme.atlassian.net/wiki")
    monkeypatch.setattr(confluence_read.config, "confluence_username", lambda: "e@acme.com")
    monkeypatch.setattr(confluence_read.config, "confluence_api_key", lambda: "tok")
    tools = confluence_read.confluence_read_tools()
    assert tools, "expected a ConfluenceTools instance"
    fns = set(tools[0].functions.keys())
    assert "create_page" not in fns and "update_page" not in fns
    assert "get_page_content" in fns
