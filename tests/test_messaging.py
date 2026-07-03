"""Agentic send/schedule messaging — Bott should actually send a message or set a one-off
reminder (it has chat:write + a scheduler), not deflect to Slack slash-commands."""

from __future__ import annotations

import time
from types import SimpleNamespace

from bott.skills import messaging as m


def test_parse_when_now_and_relative_and_iso():
    assert m._parse_when("") is None
    assert m._parse_when("now") is None
    got = m._parse_when("in 2 minutes")
    assert got is not None and abs(got - (int(time.time()) + 120)) <= 3
    assert abs(m._parse_when("in 1 hour") - (int(time.time()) + 3600)) <= 3
    assert abs(m._parse_when("in 30 seconds") - (int(time.time()) + 30)) <= 3
    assert m._parse_when("not a time") is None


def test_extract_ids():
    assert m._extract_user_id("<@U028YHWMZ|Bassam Ismail>") == "U028YHWMZ"
    assert m._extract_user_id("U028YHWMZ") == "U028YHWMZ"
    assert m._extract_user_id("#general") is None
    assert m._extract_channel_id("<#C0ATHDGRD1C|bott-testing>") == "C0ATHDGRD1C"
    assert m._extract_channel_id("C0ATHDGRD1C") == "C0ATHDGRD1C"


class _FakeClient:
    def __init__(self):
        self.posted = []
        self.scheduled = []

    def chat_postMessage(self, **kw):
        self.posted.append(kw)
        return {"ok": True}

    def chat_scheduleMessage(self, **kw):
        self.scheduled.append(kw)
        return {"ok": True}


def _ctx(channel="C_CUR"):
    return SimpleNamespace(dependencies={"Slack channel_id": channel}, user_id="me@x.com")


def test_send_now_to_current_channel(monkeypatch):
    fc = _FakeClient()
    monkeypatch.setattr(m, "_client", lambda: fc)
    out = m._send_impl(_ctx(), "me", "Hi-I am Bott", "")
    assert fc.posted and fc.posted[0]["channel"] == "C_CUR"
    assert "Hi-I am Bott" in fc.posted[0]["text"]
    assert "sent" in out.lower()


def test_send_to_user_pings_them_in_channel(monkeypatch):
    fc = _FakeClient()
    monkeypatch.setattr(m, "_client", lambda: fc)
    m._send_impl(_ctx(), "<@U028YHWMZ|Bassam Ismail>", "Hi, I am bot", "")
    assert fc.posted[0]["text"].startswith("<@U028YHWMZ> ")


def test_scheduled_send_uses_schedule_api(monkeypatch):
    fc = _FakeClient()
    monkeypatch.setattr(m, "_client", lambda: fc)
    out = m._send_impl(_ctx(), "me", "reminder!", "in 2 minutes")
    assert not fc.posted and fc.scheduled
    assert fc.scheduled[0]["post_at"] >= int(time.time()) + 100
    assert "send" in out.lower() or "remind" in out.lower()


def test_explicit_channel_target(monkeypatch):
    fc = _FakeClient()
    monkeypatch.setattr(m, "_client", lambda: fc)
    m._send_impl(_ctx(), "<#C999|wg-bott>", "hello team", "")
    assert fc.posted[0]["channel"] == "C999"
