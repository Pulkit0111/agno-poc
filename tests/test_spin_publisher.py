"""Publisher selection, Spin deploy, and Slack fallback."""

from __future__ import annotations

import pytest

from bott.shared import config
from bott.shared.integrations import spin
from bott.shared.integrations.spin import (
    SlackDraftPublisher,
    SpinStaticPublisher,
    get_publisher,
)


def test_factory_picks_spin_when_configured(monkeypatch):
    monkeypatch.setattr(config, "spin_api_base_url", lambda: "https://spin")
    monkeypatch.setattr(config, "spin_api_token", lambda: "tok")
    monkeypatch.setattr(config, "spin_group", lambda: "axelerant")
    assert isinstance(get_publisher(), SpinStaticPublisher)


def test_factory_falls_back_to_slack(monkeypatch):
    monkeypatch.setattr(config, "spin_api_base_url", lambda: None)
    monkeypatch.setattr(config, "spin_api_token", lambda: None)
    assert isinstance(get_publisher(), SlackDraftPublisher)


def test_spin_publish_posts_files_and_returns_url(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"url": "https://padi-sprint-1-report.public.spin.axelerant.tech/v/v-1/"}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["auth"] = headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr(spin.httpx, "post", fake_post)
    pub = SpinStaticPublisher("https://spin", "tok", group="axelerant")
    result = pub.publish("padi-sprint-1-report", "PADI", "<html></html>")
    assert result.mode == "spin"
    assert result.url.endswith("/v/v-1/")
    assert captured["json"]["files"]["index.html"] == "<html></html>"
    assert captured["json"]["public"] is True
    assert captured["auth"] == "Bearer tok"


def test_spin_publish_raises_when_no_url(monkeypatch):
    class _Resp:
        text = "{}"

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    monkeypatch.setattr(spin.httpx, "post", lambda *a, **k: _Resp())
    with pytest.raises(RuntimeError):
        SpinStaticPublisher("https://spin", "tok").publish("s", "t", "<html>")


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
