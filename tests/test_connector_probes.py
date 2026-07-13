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
    last_kwargs = None

    def __init__(self, spaces=None, error=None, **kwargs):
        _StubAtlassianConfluence.last_kwargs = kwargs
        self._spaces = spaces if spaces is not None else {"results": [{"key": "ENG"}]}
        self._error = error

    def get_all_spaces(self, start=0, limit=50, expand=None, space_type=None, space_status=None):
        if self._error:
            raise self._error
        return self._spaces


def _configure_confluence(monkeypatch, client_cls=_StubAtlassianConfluence):
    import atlassian

    monkeypatch.setattr(probes.config, "confluence_configured", lambda: True)
    monkeypatch.setattr(probes.config, "confluence_url", lambda: "https://x.atlassian.net/wiki")
    monkeypatch.setattr(probes.config, "confluence_username", lambda: "bot@x.com")
    monkeypatch.setattr(probes.config, "confluence_api_key", lambda: "tok")
    monkeypatch.setattr(atlassian, "Confluence", client_cls)
    _StubAtlassianConfluence.last_kwargs = None


def test_confluence_not_configured(monkeypatch):
    monkeypatch.setattr(probes.config, "confluence_configured", lambda: False)
    out = probes.probe("confluence")
    assert out == {"ok": False, "message": "Confluence isn't configured (set CONFLUENCE_URL + credentials)."}


def test_confluence_success(monkeypatch):
    _configure_confluence(monkeypatch)
    out = probes.probe("confluence")
    assert out == {"ok": True, "message": "Reached Confluence (1 space listed)."}


def test_confluence_probe_is_time_bounded(monkeypatch):
    """The atlassian client's default timeout is 75s — the probe must pin it to 10s."""
    _configure_confluence(monkeypatch)
    probes.probe("confluence")
    assert _StubAtlassianConfluence.last_kwargs["timeout"] == 10


def test_confluence_exception_becomes_ok_false(monkeypatch):
    class _Boom(_StubAtlassianConfluence):
        def __init__(self, **kwargs):
            super().__init__(error=RuntimeError("403 forbidden"), **kwargs)

    _configure_confluence(monkeypatch, client_cls=_Boom)
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


# ── Candidate probes (add-connector flow) — GitHub App / second Sentry org / HTTP API ──

class _FakeResp:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_probe_candidate_unknown_kind_raises_key_error():
    with pytest.raises(KeyError):
        probes.probe_candidate("not-a-kind", {})


def test_github_app_candidate_success(monkeypatch):
    import httpx

    from bott.agents.code_review.github import app_auth

    monkeypatch.setattr(app_auth, "_app_jwt", lambda app_id, pem: "jwt-token")
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(200, {"name": "Bott Reviewer"}))
    out = probes.probe_candidate("github_app", {"app_id": "1", "private_key": "PEM"})
    assert out == {"ok": True, "message": "Connected to GitHub App 'Bott Reviewer'."}


def test_github_app_candidate_bad_key_fails(monkeypatch):
    from bott.agents.code_review.github import app_auth

    def boom(app_id, pem):
        raise ValueError("Could not deserialize key data")

    monkeypatch.setattr(app_auth, "_app_jwt", boom)
    out = probes.probe_candidate("github_app", {"app_id": "1", "private_key": "not-a-pem"})
    assert out["ok"] is False
    assert "Could not deserialize key data" in out["message"]


def test_github_app_candidate_http_failure(monkeypatch):
    import httpx

    from bott.agents.code_review.github import app_auth

    monkeypatch.setattr(app_auth, "_app_jwt", lambda app_id, pem: "jwt-token")
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(401))
    out = probes.probe_candidate("github_app", {"app_id": "1", "private_key": "PEM"})
    assert out["ok"] is False
    assert "401" in out["message"]


def test_sentry_org_candidate_success(monkeypatch):
    from bott.shared.integrations.sentry import SentryClient

    monkeypatch.setattr(SentryClient, "list_issues", lambda self, query="is:unresolved", limit=20: [])
    out = probes.probe_candidate("sentry_org", {"org": "secondorg", "auth_token": "tok", "base_url": "https://sentry.io"})
    assert out == {"ok": True, "message": "Reached Sentry org 'secondorg'."}


def test_sentry_org_candidate_failure(monkeypatch):
    from bott.shared.integrations.sentry import SentryClient

    def boom(self, query="is:unresolved", limit=20):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(SentryClient, "list_issues", boom)
    out = probes.probe_candidate("sentry_org", {"org": "secondorg", "auth_token": "bad", "base_url": "https://sentry.io"})
    assert out["ok"] is False
    assert "401 unauthorized" in out["message"]


def test_http_api_candidate_success(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(404))
    out = probes.probe_candidate("http_api", {"base_url": "https://api.example.com/health"})
    assert out == {"ok": True, "message": "Reached https://api.example.com/health (HTTP 404)."}


def test_http_api_candidate_server_error_fails(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(503))
    out = probes.probe_candidate("http_api", {"base_url": "https://api.example.com/health"})
    assert out["ok"] is False
    assert "503" in out["message"]


def test_http_api_candidate_passes_header(monkeypatch):
    import httpx

    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["headers"] = headers
        return _FakeResp(200)

    monkeypatch.setattr(httpx, "get", fake_get)
    probes.probe_candidate("http_api", {
        "base_url": "https://api.example.com", "header_name": "X-Api-Key", "header_value": "secret",
    })
    assert seen["headers"] == {"X-Api-Key": "secret"}


# ── SSRF tripwire — the link-local/metadata range is never probed ────────────────────

def _get_must_not_be_called(url, headers=None, timeout=None):
    raise AssertionError("network GET must not happen for a refused host")


@pytest.mark.parametrize("base_url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.1.1/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata.goog/",
    "http://[fe80::1]/",
])
def test_http_api_candidate_refuses_metadata_hosts_without_probing(monkeypatch, base_url):
    import httpx

    monkeypatch.setattr(httpx, "get", _get_must_not_be_called)
    out = probes.probe_candidate("http_api", {"base_url": base_url})
    assert out["ok"] is False
    assert "not allowed" in out["message"] or "aren't allowed" in out["message"]


def test_sentry_org_candidate_refuses_metadata_base_url_without_probing(monkeypatch):
    from bott.shared.integrations.sentry import SentryClient

    def boom(self, query="is:unresolved", limit=20):
        raise AssertionError("network call must not happen for a refused host")

    monkeypatch.setattr(SentryClient, "list_issues", boom)
    out = probes.probe_candidate("sentry_org", {
        "org": "acme", "auth_token": "t", "base_url": "http://169.254.169.254/",
    })
    assert out["ok"] is False
    assert "aren't allowed" in out["message"]


def test_http_api_candidate_allows_private_range_hosts(monkeypatch):
    """RFC-1918 is deliberately ALLOWED — internal APIs are a legitimate target for the
    custom-HTTP connector (see the SSRF note in probes.py); only link-local/metadata is
    refused."""
    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(200))
    out = probes.probe_candidate("http_api", {"base_url": "http://10.0.0.5/health"})
    assert out["ok"] is True


# ── Stored (console-added) connectors re-probed by name ───────────────────────────────

def test_probe_of_unknown_name_still_raises_key_error(monkeypatch):
    from bott.shared import connector_credentials

    monkeypatch.setattr(connector_credentials, "load", lambda name: None)
    with pytest.raises(KeyError):
        probes.probe("not-a-real-connector")


def test_probe_stored_github_app(monkeypatch):
    import httpx

    from bott.agents.code_review.github import app_auth
    from bott.shared import connector_credentials

    monkeypatch.setattr(connector_credentials, "load",
                        lambda name: {"app_id": "1", "installation_id": None, "private_key": "PEM"} if name == "github-app" else None)
    monkeypatch.setattr(app_auth, "_app_jwt", lambda app_id, pem: "jwt-token")
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(200, {"name": "Bott"}))
    out = probes.probe("github-app")
    assert out == {"ok": True, "message": "Connected to GitHub App 'Bott'."}


def test_probe_stored_sentry_org(monkeypatch):
    from bott.shared import connector_credentials
    from bott.shared.integrations.sentry import SentryClient

    monkeypatch.setattr(connector_credentials, "load",
                        lambda name: {"org": "secondorg", "auth_token": "t", "base_url": "https://sentry.io"} if name == "sentry-secondorg" else None)
    monkeypatch.setattr(SentryClient, "list_issues", lambda self, query="is:unresolved", limit=20: [])
    out = probes.probe("sentry-secondorg")
    assert out == {"ok": True, "message": "Reached Sentry org 'secondorg'."}


def test_probe_stored_http_api(monkeypatch):
    import httpx

    from bott.shared import connector_credentials

    monkeypatch.setattr(connector_credentials, "load",
                        lambda name: {"base_url": "https://api.example.com"} if name == "http-myapi" else None)
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _FakeResp(200))
    out = probes.probe("http-myapi")
    assert out["ok"] is True


def test_probe_stored_name_recognized_but_nothing_stored_raises_key_error(monkeypatch):
    """'sentry-ghost' matches the naming convention but was removed/never stored — still
    a genuine 'unknown connector' from the caller's perspective, not a probe failure."""
    from bott.shared import connector_credentials

    monkeypatch.setattr(connector_credentials, "load", lambda name: None)
    with pytest.raises(KeyError):
        probes.probe("sentry-ghost")


# ── Secret redaction — probe messages surface in the console drawer ──────────────────

_FAKE_SLACK_TOKEN = "xoxb-1234567890-abcdefABCDEF"


def test_probe_message_redacts_tokens_from_exceptions(monkeypatch):
    """An SDK error that echoes a credential back must NOT leak it into the UI-visible
    message — probe() redacts every exception-derived message, not just the log line."""
    from bott.shared.integrations.jira import JiraClient

    monkeypatch.setattr(probes.config, "jira_configured", lambda: True)
    monkeypatch.setattr(probes.config, "jira_base_url", lambda: "https://x.atlassian.net")
    monkeypatch.setattr(probes.config, "jira_email", lambda: "bot@x.com")
    monkeypatch.setattr(probes.config, "jira_api_token", lambda: "tok")
    monkeypatch.setattr(probes.config, "jira_story_points_field", lambda: None)

    def boom(self, path, params=None, **kw):
        raise RuntimeError(f"401 unauthorized for token {_FAKE_SLACK_TOKEN}")

    monkeypatch.setattr(JiraClient, "_get", boom)
    out = probes.probe("jira")
    assert out["ok"] is False
    assert _FAKE_SLACK_TOKEN not in out["message"]
    assert "401 unauthorized" in out["message"]  # the useful part survives redaction


def test_google_per_scope_message_redacts_tokens(monkeypatch):
    """_google()'s per-scope catch builds message strings too — same redaction rule."""
    from bott.skills.connectors import calendar as calendar_mod
    from bott.skills.connectors import drive as drive_mod
    from bott.skills.connectors import gmail as gmail_mod

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail_mod, "_impersonated",
                        lambda rc: _StubGoogleClient(error=RuntimeError(f"denied, token {_FAKE_SLACK_TOKEN}")))
    monkeypatch.setattr(drive_mod, "_impersonated", lambda rc: _StubGoogleClient())
    monkeypatch.setattr(calendar_mod, "_impersonated", lambda rc: _StubGoogleClient())

    out = probes.probe("google", "admin@x.com")
    assert out["ok"] is False
    assert _FAKE_SLACK_TOKEN not in out["message"]
    assert "denied" in out["message"]


# ── Hard deadline — probes must never hang the Test endpoint ─────────────────────────

def test_with_deadline_times_out_and_probe_reports_it(monkeypatch):
    import time

    def hang():
        time.sleep(2)

    with pytest.raises(TimeoutError, match="timed out"):
        probes._with_deadline(hang, seconds=0.1)


def test_gmail_probe_timeout_becomes_ok_false(monkeypatch):
    """A hung Google client (no timeout knob in googleapiclient) is cut off by the
    deadline wrapper and reported as a plain probe failure."""
    from bott.skills.connectors import gmail as gmail_mod

    class _Hang:
        def search_emails(self, query, limit):
            import time
            time.sleep(2)

    monkeypatch.setattr(probes.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(probes, "_DEADLINE", 0.1)
    monkeypatch.setattr(gmail_mod, "_impersonated", lambda rc: _Hang())
    out = probes.probe("gmail", "admin@x.com")
    assert out["ok"] is False
    assert "timed out" in out["message"]
