"""Aggregator connector_tools() — gates all off; includes slack when token present."""

from bott.skills import connectors


def test_aggregator_gates_all_off(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.jira_read as jr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    assert connectors.connector_tools() == []


def test_aggregator_includes_slack_when_token_present(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.jira_read as jr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    names = {getattr(t, "__name__", "") for t in connectors.connector_tools()}
    assert "read_slack_thread" in names


def test_gmail_registered_and_listed(monkeypatch):
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    assert "gmail" in REGISTRY.list_names()["user"]
    assert {"jira", "confluence", "slack", "memra"} <= set(REGISTRY.list_names()["org"])


def test_gmail_wired_when_configured(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.gmail as gmail
    import bott.skills.connectors.jira_read as jr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.setattr(gmail.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail.config, "google_service_account_path", lambda: "/tmp/sa.json")

    class _Stub:
        def __init__(self, **k): pass

    monkeypatch.setattr(gmail, "GmailTools", _Stub)
    from bott.skills import connectors
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in connectors.connector_tools()}
    assert "gmail_search" in names and "gmail_read_thread" in names


def test_register_all_idempotent():
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    n = len(REGISTRY.all_connectors())
    register_all()
    assert len(REGISTRY.all_connectors()) == n


def test_drive_and_calendar_registered_and_listed():
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    user = REGISTRY.list_names()["user"]
    assert "drive" in user and "calendar" in user and "gmail" in user


def test_drive_calendar_wired_when_configured(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.jira_read as jr
    import bott.skills.connectors.drive as drive
    import bott.skills.connectors.calendar as calendar
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    for mod in (drive, calendar):
        monkeypatch.setattr(mod.config, "google_delegation_configured", lambda: True)
        monkeypatch.setattr(mod.config, "google_service_account_path", lambda: "/tmp/sa.json")

    class _S:
        def __init__(self, **k): pass

    monkeypatch.setattr(drive, "GoogleDriveTools", _S)
    monkeypatch.setattr(calendar, "GoogleCalendarTools", _S)
    from bott.skills import connectors
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in connectors.connector_tools()}
    assert {"drive_search", "drive_read_file", "calendar_list_events",
            "calendar_get_event", "calendar_list_calendars"} <= names
