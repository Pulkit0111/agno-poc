"""Publisher selection, Spin deploy, and Slack fallback."""

from __future__ import annotations

from bott.shared import config
from bott.shared.integrations import spin
from bott.shared.integrations.spin import (
    SlackDraftPublisher,
    SpinStaticPublisher,
    get_publisher,
)


def test_factory_picks_spin_when_configured(monkeypatch):
    monkeypatch.setattr(config, "spin_api_token", lambda: "spk_x")
    assert isinstance(get_publisher(), SpinStaticPublisher)


def test_factory_falls_back_to_slack(monkeypatch):
    monkeypatch.setattr(config, "spin_api_token", lambda: None)
    assert isinstance(get_publisher(), SlackDraftPublisher)


def test_slugify_obeys_spin_rules():
    assert spin._slugify("PADI/WebImplementation — Sprint 1") == "padi-webimplementation-sprint-1"
    assert len(spin._slugify("x" * 60)) <= 32


def test_spin_publish_creates_project_deploys_and_returns_public_url(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    def fake_request(method, url, json=None, headers=None, timeout=None):
        calls.append((method, url, json, headers.get("Authorization")))
        if method == "GET":  # no existing project
            return _Resp({"projects": []})
        if url.endswith("/v1/projects"):  # create
            return _Resp({"project_id": "pid-123"})
        return _Resp({"live_url": "https://x.spin.axelerant.tech/", "version_id": "v-9"})  # deploy

    monkeypatch.setattr(spin.httpx, "request", fake_request)
    pub = SpinStaticPublisher("https://platform-api.spin.axelerant.tech", "spk_x",
                              "public.spin.axelerant.tech")
    result = pub.publish("padi-sprint-1-report", "PADI Sprint 1", "<html>hi</html>")

    assert result.mode == "spin"
    assert result.url == "https://padi-sprint-1-report.public.spin.axelerant.tech/"
    # created project + deployed base64 of the html
    create = next(c for c in calls if c[0] == "POST" and c[1].endswith("/v1/projects"))
    assert create[2]["subdomain"] == "padi-sprint-1-report" and create[2]["public"] is True
    deploy = next(c for c in calls if c[1].endswith("/deploy"))
    import base64
    assert deploy[2]["files"]["index.html"] == base64.b64encode(b"<html>hi</html>").decode()
    assert deploy[3] == "Bearer spk_x"


def test_spin_publish_reuses_existing_project(monkeypatch):
    seen = {"created": False}

    class _Resp:
        def __init__(self, p):
            self._p = p

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    def fake_request(method, url, json=None, headers=None, timeout=None):
        if method == "GET":
            return _Resp({"projects": [{"subdomain": "padi-sprint-1-report", "project_id": "pid-existing"}]})
        if method == "POST" and url.endswith("/v1/projects"):
            seen["created"] = True
            return _Resp({"project_id": "should-not-happen"})
        return _Resp({"live_url": "https://x/", "version_id": "v-2"})

    monkeypatch.setattr(spin.httpx, "request", fake_request)
    pub = SpinStaticPublisher("https://platform-api.spin.axelerant.tech", "spk_x", "public.spin.axelerant.tech")
    pub.publish("padi-sprint-1-report", "PADI", "<html>")
    assert seen["created"] is False  # reused the existing project, didn't recreate


def test_slack_draft_needs_channel():
    res = SlackDraftPublisher("xoxb-x").publish("s", "t", "<html>", channel="")
    assert res.mode == "slack-draft" and res.url is None


def test_slack_draft_degrades_to_message_when_upload_scope_missing(monkeypatch):
    """No files:write scope -> don't raise; post a chat message explaining instead."""
    import slack_sdk

    calls = {"upload": 0, "message": 0, "text": ""}

    class FakeClient:
        def __init__(self, token=None):
            pass

        def files_upload_v2(self, **k):
            calls["upload"] += 1
            raise RuntimeError("missing_scope: files:write")

        def chat_postMessage(self, **k):
            calls["message"] += 1
            calls["text"] = k.get("text", "")

    monkeypatch.setattr(slack_sdk, "WebClient", FakeClient)
    res = SlackDraftPublisher("xoxb").publish("s", "Sprint Report", "<html>", channel="C1")
    assert res.mode == "slack-draft" and res.url is None
    assert calls["upload"] == 1 and calls["message"] == 1  # tried upload, then messaged
    assert "files:write" in calls["text"]
