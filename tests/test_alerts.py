"""alert_admins / alert_admins_throttled: best-effort Slack DMs to configured admins."""

from __future__ import annotations

import threading

import pytest

from bott.shared import alerts


class _FakeClient:
    def __init__(self):
        self.dms: list[tuple[str, str]] = []
        self.emails: dict[str, str] = {}

    def users_lookupByEmail(self, email):
        if email not in self.emails:
            from slack_sdk.errors import SlackApiError
            raise SlackApiError("user_not_found", {"ok": False, "error": "users_not_found"})
        return {"user": {"id": self.emails[email]}}

    def chat_postMessage(self, channel, text):
        self.dms.append((channel, text))


@pytest.fixture(autouse=True)
def _reset_cooldowns():
    alerts._last_sent.clear()
    yield
    alerts._last_sent.clear()


def test_no_admins_configured_is_a_noop(monkeypatch):
    monkeypatch.setattr(alerts, "bott_admins", lambda: set())
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    alerts.alert_admins("something broke")  # must not raise


def test_no_slack_token_is_a_noop(monkeypatch):
    monkeypatch.setattr(alerts, "bott_admins", lambda: {"admin@x.com"})
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    alerts.alert_admins("something broke")  # must not raise


def test_dms_every_configured_admin(monkeypatch):
    monkeypatch.setattr(alerts, "bott_admins", lambda: {"a@x.com", "b@x.com"})
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    fake = _FakeClient()
    fake.emails = {"a@x.com": "U_A", "b@x.com": "U_B"}
    monkeypatch.setattr("slack_sdk.WebClient", lambda token: fake)
    alerts.alert_admins("the sky is falling")
    assert set(fake.dms) == {("U_A", "the sky is falling"), ("U_B", "the sky is falling")}


def test_unknown_admin_email_does_not_block_the_others(monkeypatch):
    monkeypatch.setattr(alerts, "bott_admins", lambda: {"missing@x.com", "b@x.com"})
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    fake = _FakeClient()
    fake.emails = {"b@x.com": "U_B"}
    monkeypatch.setattr("slack_sdk.WebClient", lambda token: fake)
    alerts.alert_admins("partial failure ok")
    assert fake.dms == [("U_B", "partial failure ok")]


def test_throttle_drops_repeat_alerts_within_cooldown(monkeypatch):
    monkeypatch.setattr(alerts, "bott_admins", lambda: {"a@x.com"})
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    fake = _FakeClient()
    fake.emails = {"a@x.com": "U_A"}
    monkeypatch.setattr("slack_sdk.WebClient", lambda token: fake)
    alerts.alert_admins_throttled("codex-down", "codex is down", cooldown_s=900)
    alerts.alert_admins_throttled("codex-down", "codex is down", cooldown_s=900)
    assert len(fake.dms) == 1, "second call within the cooldown must not send a duplicate DM"


def test_throttle_uses_separate_cooldowns_per_key(monkeypatch):
    monkeypatch.setattr(alerts, "bott_admins", lambda: {"a@x.com"})
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    fake = _FakeClient()
    fake.emails = {"a@x.com": "U_A"}
    monkeypatch.setattr("slack_sdk.WebClient", lambda token: fake)
    alerts.alert_admins_throttled("codex-down", "codex is down", cooldown_s=900)
    alerts.alert_admins_throttled("job-failed", "a job failed", cooldown_s=900)
    assert len(fake.dms) == 2


def test_throttle_is_race_safe_across_threads(monkeypatch):
    """Regression: build_model() can be called concurrently from multiple threads (a Slack
    chat request and the PR-review worker thread both discovering a dead Codex login at
    once). A bare read-then-write on the cooldown dict let both slip through the check
    before either recorded its send — the exact bug behind the duplicate Slack DMs seen in
    production (two identical alerts landing back-to-back)."""
    monkeypatch.setattr(alerts, "bott_admins", lambda: {"a@x.com"})
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    fake = _FakeClient()
    fake.emails = {"a@x.com": "U_A"}
    monkeypatch.setattr("slack_sdk.WebClient", lambda token: fake)

    barrier = threading.Barrier(20)

    def fire():
        barrier.wait()  # maximize the chance every thread hits the check at the same instant
        alerts.alert_admins_throttled("codex-down", "codex is down", cooldown_s=900)

    threads = [threading.Thread(target=fire) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(fake.dms) == 1, f"expected exactly one DM, got {len(fake.dms)}"
