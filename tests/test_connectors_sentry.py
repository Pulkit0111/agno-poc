import bott.skills.connectors.sentry_read as sentry_read
from bott.shared.integrations.sentry import SentryClient


def _client(monkeypatch, raw):
    c = SentryClient(base_url="https://sentry.io", org_slug="acme", api_token="t")
    monkeypatch.setattr(c, "_get", lambda path, params=None: raw)
    return c


def test_list_issues_normalizes(monkeypatch):
    raw = [{"id": "1", "shortId": "ACME-1", "title": "Boom", "level": "error",
            "status": "unresolved", "count": "42", "permalink": "https://s/1"}]
    c = _client(monkeypatch, raw)
    out = c.list_issues()
    assert out and out[0]["id"] == "1" and out[0]["shortId"] == "ACME-1"
    assert out[0]["title"] == "Boom" and out[0]["count"] == "42"


def test_get_issue_normalizes(monkeypatch):
    raw = {"id": "9", "shortId": "ACME-9", "title": "NPE", "level": "error",
           "status": "unresolved", "count": "3"}
    c = _client(monkeypatch, raw)
    out = c.get_issue("9")
    assert out["id"] == "9" and out["title"] == "NPE"


def test_issue_events_normalizes_and_limits(monkeypatch):
    raw = [{"eventID": f"e{i}", "message": f"m{i}", "dateCreated": "2026-01-01",
            "tags": []} for i in range(10)]
    c = _client(monkeypatch, raw)
    out = c.issue_events("9", limit=3)
    assert len(out) == 3 and out[0]["eventID"] == "e0"


def test_normalizers_tolerate_missing_keys(monkeypatch):
    c = _client(monkeypatch, [{"id": "1"}])
    out = c.list_issues()
    assert out[0]["id"] == "1"  # no KeyError on absent title/level/count


def test_tools_gate_when_unconfigured(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: False)
    assert "isn't configured" in sentry_read.sentry_list_issues().lower()
    assert "isn't configured" in sentry_read.sentry_get_issue("1").lower()
    assert "isn't configured" in sentry_read.sentry_issue_events("1").lower()
    assert sentry_read.sentry_read_tools() == []


def test_tools_present_when_configured(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: True)
    names = {getattr(t, "__name__", "") for t in sentry_read.sentry_read_tools()}
    assert names == {"sentry_list_issues", "sentry_get_issue", "sentry_issue_events"}


def test_list_tool_formats(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: True)

    class _Stub:
        def list_issues(self, query="is:unresolved", limit=20):
            return [{"id": "1", "shortId": "ACME-1", "title": "Boom", "level": "error",
                     "count": "42", "permalink": "https://s/1", "status": "unresolved"}]

    monkeypatch.setattr(sentry_read, "_client", lambda: _Stub())
    out = sentry_read.sentry_list_issues()
    assert "ACME-1" in out and "Boom" in out


def test_tool_error_is_readable_and_redacted(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: True)

    class _Boom:
        def list_issues(self, *a, **k):
            raise RuntimeError("token=sk-secret failed")

    monkeypatch.setattr(sentry_read, "_client", lambda: _Boom())

    # Spy on redact: record calls but delegate to the real implementation.
    real_redact = sentry_read.redact
    redact_calls = []

    def spy_redact(s):
        redact_calls.append(s)
        return real_redact(s)

    monkeypatch.setattr(sentry_read, "redact", spy_redact)

    out = sentry_read.sentry_list_issues()
    assert "sk-secret" not in out
    assert "sentry" in out.lower()  # readable message names the system
    # Prove redact() was actually called with the raw error string.
    assert redact_calls, "redact() was never called"
    assert any("sk-secret" in call for call in redact_calls), (
        f"redact() was not called with the raw error text; calls: {redact_calls}"
    )
