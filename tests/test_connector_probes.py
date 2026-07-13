"""Unit tests for live connector health probes — every underlying client call is
monkeypatched, so nothing here ever touches the network."""

from __future__ import annotations

import pytest

from bott.skills.connectors import probes


def test_unknown_connector_raises_key_error():
    with pytest.raises(KeyError):
        probes.probe("not-a-real-connector")


# ── Jira ────────────────────────────────────────────────────────────────────────────

def test_jira_not_configured(monkeypatch):
    monkeypatch.setattr(probes.config, "jira_configured", lambda: False)
    out = probes.probe("jira")
    assert out == {"ok": False, "message": "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."}


def test_jira_success(monkeypatch):
    from bott.shared.integrations.jira import JiraClient

    monkeypatch.setattr(probes.config, "jira_configured", lambda: True)
    monkeypatch.setattr(probes.config, "jira_base_url", lambda: "https://x.atlassian.net")
    monkeypatch.setattr(probes.config, "jira_email", lambda: "bot@x.com")
    monkeypatch.setattr(probes.config, "jira_api_token", lambda: "tok")
    monkeypatch.setattr(probes.config, "jira_story_points_field", lambda: None)
    monkeypatch.setattr(JiraClient, "_get", lambda self, path, params=None, **kw: {"displayName": "Bott Bot"})

    out = probes.probe("jira")
    assert out == {"ok": True, "message": "Connected to Jira as Bott Bot."}


def test_jira_exception_becomes_ok_false(monkeypatch):
    from bott.shared.integrations.jira import JiraClient

    monkeypatch.setattr(probes.config, "jira_configured", lambda: True)
    monkeypatch.setattr(probes.config, "jira_base_url", lambda: "https://x.atlassian.net")
    monkeypatch.setattr(probes.config, "jira_email", lambda: "bot@x.com")
    monkeypatch.setattr(probes.config, "jira_api_token", lambda: "tok")
    monkeypatch.setattr(probes.config, "jira_story_points_field", lambda: None)

    def boom(self, path, params=None, **kw):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(JiraClient, "_get", boom)
    out = probes.probe("jira")
    assert out["ok"] is False
    assert "401 unauthorized" in out["message"]


# ── Confluence ──────────────────────────────────────────────────────────────────────

class _StubAtlassianConfluence:
    def __init__(self, spaces=None, error=None):
        self._spaces = spaces if spaces is not None else {"results": [{"key": "ENG"}]}
        self._error = error

    def get_all_spaces(self, start=0, limit=50, expand=None, space_type=None, space_status=None):
        if self._error:
            raise self._error
        return self._spaces


class _StubConfluenceTools:
    def __init__(self, **kwargs):
        self.confluence = _StubAtlassianConfluence()


def test_confluence_not_configured(monkeypatch):
    monkeypatch.setattr(probes.config, "confluence_configured", lambda: False)
    out = probes.probe("confluence")
    assert out == {"ok": False, "message": "Confluence isn't configured (set CONFLUENCE_URL + credentials)."}


def test_confluence_success(monkeypatch):
    import agno.tools.confluence as confluence_mod

    monkeypatch.setattr(probes.config, "confluence_configured", lambda: True)
    monkeypatch.setattr(probes.config, "confluence_url", lambda: "https://x.atlassian.net/wiki")
    monkeypatch.setattr(probes.config, "confluence_username", lambda: "bot@x.com")
    monkeypatch.setattr(probes.config, "confluence_api_key", lambda: "tok")
    monkeypatch.setattr(confluence_mod, "ConfluenceTools", _StubConfluenceTools)

    out = probes.probe("confluence")
    assert out == {"ok": True, "message": "Reached Confluence (1 space listed)."}


def test_confluence_exception_becomes_ok_false(monkeypatch):
    import agno.tools.confluence as confluence_mod

    class _Boom(_StubConfluenceTools):
        def __init__(self, **kwargs):
            self.confluence = _StubAtlassianConfluence(error=RuntimeError("403 forbidden"))

    monkeypatch.setattr(probes.config, "confluence_configured", lambda: True)
    monkeypatch.setattr(probes.config, "confluence_url", lambda: "https://x.atlassian.net/wiki")
    monkeypatch.setattr(probes.config, "confluence_username", lambda: "bot@x.com")
    monkeypatch.setattr(probes.config, "confluence_api_key", lambda: "tok")
    monkeypatch.setattr(confluence_mod, "ConfluenceTools", _Boom)

    out = probes.probe("confluence")
    assert out["ok"] is False
    assert "403 forbidden" in out["message"]


# ── Slack ───────────────────────────────────────────────────────────────────────────

class _StubWebClient:
    def __init__(self, token=None, timeout=None, error=None):
        self.token = token
        self._error = error

    def auth_test(self):
        if self._error:
            raise self._error
        return {"team": "Axelerant"}


def test_slack_not_configured(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    out = probes.probe("slack")
    assert out == {"ok": False, "message": "Slack isn't configured (set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET)."}


def test_slack_success(monkeypatch):
    import slack_sdk

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "s")
    monkeypatch.setattr(slack_sdk, "WebClient", _StubWebClient)
    out = probes.probe("slack")
    assert out == {"ok": True, "message": "Connected to Slack as the bot in Axelerant."}


def test_slack_exception_becomes_ok_false(monkeypatch):
    import slack_sdk

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "s")
    monkeypatch.setattr(
        slack_sdk, "WebClient",
        lambda **kw: _StubWebClient(error=RuntimeError("invalid_auth")),
    )
    out = probes.probe("slack")
    assert out["ok"] is False
    assert "invalid_auth" in out["message"]


# ── Memra ───────────────────────────────────────────────────────────────────────────

def test_memra_not_configured(monkeypatch):
    monkeypatch.setattr(probes.config, "memra_configured", lambda: False)
    out = probes.probe("memra")
    assert out == {"ok": False, "message": "Memra isn't configured (set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET)."}


def test_memra_success(monkeypatch):
    from bott.shared.context import memra as memra_mod

    monkeypatch.setattr(probes.config, "memra_configured", lambda: True)
    monkeypatch.setattr(memra_mod.MemraClient, "list_tools", lambda self: ["ask_context", "get_person"])
    out = probes.probe("memra")
    assert out == {"ok": True, "message": "Reached Memra (2 tool(s) available)."}


def test_memra_exception_becomes_ok_false(monkeypatch):
    from bott.shared.context import memra as memra_mod

    monkeypatch.setattr(probes.config, "memra_configured", lambda: True)

    def boom(self):
        raise memra_mod.MemraError("token request failed: 401")

    monkeypatch.setattr(memra_mod.MemraClient, "list_tools", boom)
    out = probes.probe("memra")
    assert out["ok"] is False
    assert "401" in out["message"]


# ── Sentry ──────────────────────────────────────────────────────────────────────────

def test_sentry_not_configured(monkeypatch):
    monkeypatch.setattr(probes.config, "sentry_configured", lambda: False)
    out = probes.probe("sentry")
    assert out == {"ok": False, "message": "Sentry isn't configured (set SENTRY_ORG_SLUG + SENTRY_API_TOKEN)."}


def test_sentry_success(monkeypatch):
    from bott.shared.integrations.sentry import SentryClient

    monkeypatch.setattr(probes.config, "sentry_configured", lambda: True)
    monkeypatch.setattr(probes.config, "sentry_base_url", lambda: "https://sentry.io")
    monkeypatch.setattr(probes.config, "sentry_org_slug", lambda: "axelerant")
    monkeypatch.setattr(probes.config, "sentry_api_token", lambda: "tok")
    monkeypatch.setattr(SentryClient, "list_issues", lambda self, query="is:unresolved", limit=20: [])

    out = probes.probe("sentry")
    assert out == {"ok": True, "message": "Reached Sentry org 'axelerant'."}


def test_sentry_exception_becomes_ok_false(monkeypatch):
    from bott.shared.integrations.sentry import SentryClient

    monkeypatch.setattr(probes.config, "sentry_configured", lambda: True)
    monkeypatch.setattr(probes.config, "sentry_base_url", lambda: "https://sentry.io")
    monkeypatch.setattr(probes.config, "sentry_org_slug", lambda: "axelerant")
    monkeypatch.setattr(probes.config, "sentry_api_token", lambda: "tok")

    def boom(self, query="is:unresolved", limit=20):
        raise RuntimeError("404 org not found")

    monkeypatch.setattr(SentryClient, "list_issues", boom)
    out = probes.probe("sentry")
    assert out["ok"] is False
    assert "404 org not found" in out["message"]


# ── Codex (no network) ───────────────────────────────────────────────────────────────

def test_codex_connected(monkeypatch):
    monkeypatch.setattr(probes.codex_tokens, "is_connected", lambda: True)
    out = probes.probe("codex")
    assert out == {"ok": True, "message": "Codex is connected — using the org's ChatGPT subscription."}


def test_codex_not_connected(monkeypatch):
    monkeypatch.setattr(probes.codex_tokens, "is_connected", lambda: False)
    out = probes.probe("codex")
    assert out == {"ok": False, "message": "Codex isn't connected. An admin can connect it from the Models page."}


# ── Gmail / Drive / Calendar (domain-delegated) ─────────────────────────────────────

class _StubGoogleClient:
    def __init__(self, error=None):
        self._error = error

    def search_emails(self, query, limit):
        if self._error:
            raise self._error
        return "ok"

    def search_files(self, query, limit):
        if self._error:
            raise self._error
        return "ok"

    def list_calendars(self):
        if self._error:
            raise self._error
        return "ok"


@pytest.mark.parametrize("name,module_name", [("gmail", "gmail"), ("drive", "drive"), ("calendar", "calendar")])
def test_google_service_not_configured(monkeypatch, name, module_name):
    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: False)
    out = probes.probe(name, "admin@x.com")
    assert out["ok"] is False
    assert "GOOGLE_SERVICE_ACCOUNT_PATH" in out["message"]


@pytest.mark.parametrize("name", ["gmail", "drive", "calendar"])
def test_google_service_missing_subject_email(monkeypatch, name):
    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    out = probes.probe(name, None)
    assert out["ok"] is False
    assert "No signed-in email" in out["message"]


def test_gmail_success(monkeypatch):
    from bott.skills.connectors import gmail as gmail_mod

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail_mod, "_impersonated", lambda rc: _StubGoogleClient())
    out = probes.probe("gmail", "admin@x.com")
    assert out == {"ok": True, "message": "Delegated Gmail read succeeded for admin@x.com."}


def test_gmail_exception_becomes_ok_false(monkeypatch):
    from bott.skills.connectors import gmail as gmail_mod

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail_mod, "_impersonated", lambda rc: _StubGoogleClient(error=RuntimeError("access_denied")))
    out = probes.probe("gmail", "admin@x.com")
    assert out["ok"] is False
    assert "access_denied" in out["message"]


def test_drive_success(monkeypatch):
    from bott.skills.connectors import drive as drive_mod

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(drive_mod, "_impersonated", lambda rc: _StubGoogleClient())
    out = probes.probe("drive", "admin@x.com")
    assert out == {"ok": True, "message": "Delegated Drive read succeeded for admin@x.com."}


def test_calendar_success(monkeypatch):
    from bott.skills.connectors import calendar as calendar_mod

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(calendar_mod, "_impersonated", lambda rc: _StubGoogleClient())
    out = probes.probe("calendar", "admin@x.com")
    assert out == {"ok": True, "message": "Delegated Calendar read succeeded for admin@x.com."}


def test_google_aggregates_all_three(monkeypatch):
    from bott.skills.connectors import calendar as calendar_mod
    from bott.skills.connectors import drive as drive_mod
    from bott.skills.connectors import gmail as gmail_mod

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail_mod, "_impersonated", lambda rc: _StubGoogleClient())
    monkeypatch.setattr(drive_mod, "_impersonated", lambda rc: _StubGoogleClient())
    monkeypatch.setattr(calendar_mod, "_impersonated", lambda rc: _StubGoogleClient(error=RuntimeError("no cal scope")))

    out = probes.probe("google", "admin@x.com")
    assert out["ok"] is False  # calendar failed -> overall not ok
    assert "gmail: ok" in out["message"]
    assert "drive: ok" in out["message"]
    assert "no cal scope" in out["message"]


def test_google_not_configured(monkeypatch):
    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: False)
    out = probes.probe("google", "admin@x.com")
    assert out["ok"] is False
    assert "GOOGLE_SERVICE_ACCOUNT_PATH" in out["message"]


def test_google_missing_subject_email(monkeypatch):
    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    out = probes.probe("google", None)
    assert out["ok"] is False
    assert "No signed-in email" in out["message"]
