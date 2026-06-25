"""Sprint-report tools: dynamic engagement resolution, narrative parsing, metric integrity."""

from __future__ import annotations

from bott.shared import config
from bott.shared.integrations.spin import PublishResult
from bott.skills.sprint_report import tool
from bott.skills.sprint_report.render import Metrics, ReportMeta
from bott.skills.sprint_report.tool import Dossier, Engagement


def _eng():
    # client is unused once _build_dossier is stubbed.
    return Engagement(client=None, board_id=1, project_key="PADI",
                      title="PADI Digital Overhaul", client_name="PADI", org="Axelerant",
                      slug_tmpl="padi-sprint-{n}-report", board_url="https://board")


def _dossier():
    return Dossier(
        meta=ReportMeta("PADI Digital Overhaul", "PADI", "Axelerant", "Sprint 1", "Sprint 2",
                        "1 June – 12 June 2026"),
        metrics=Metrics(13, 75, 61, 81, has_points=True),
        done_issues=[{"summary": "Frontend scaffold"}],
        next_issues=[{"summary": "JSON API", "tag": "spike"}],
        incomplete=[{"summary": "Acquia perms", "status": "Blocked"}],
        slug="padi-sprint-1-report", sprint_id=900,
    )


def test_dossier_requires_jira(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: False)
    assert "Jira isn't configured" in tool.build_sprint_dossier("PADI")


def test_unknown_engagement_lists_known(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: None)
    monkeypatch.setattr(tool, "_not_found", lambda q: f"Couldn't find a Jira board for '{q}'. Known projects: ACME, PADI.")
    out = tool.build_sprint_dossier("nope")
    assert "Couldn't find a Jira board for 'nope'" in out and "PADI" in out


def test_build_dossier_text(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())
    out = tool.build_sprint_dossier("PADI")
    assert "13 stories delivered" in out and "velocity 81%" in out
    assert "Frontend scaffold" in out and "JSON API" in out
    assert "Acquia perms" in out  # risk candidate surfaced
    assert "publish_sprint_report" in out and "Memra" in out  # next-step + channel guidance


def test_publish_bad_json(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    assert "wasn't valid" in tool.publish_sprint_report("PADI", "{not json")


def test_publish_renders_and_metrics_cannot_be_faked(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())
    monkeypatch.setattr(tool.store, "set_setting", lambda *a, **k: None)

    captured = {}

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            captured["html"] = html
            captured["slug"] = slug
            return PublishResult(mode="spin", url="https://x", detail="Published to Spin: https://x")

    monkeypatch.setattr(tool, "get_publisher", lambda: FakePub())

    # The agent tries to assert a bogus velocity in a bullet — it must NOT become a stat-card.
    report = '{"sections": [{"type": "bullets", "title": "Notes", "items": ["velocity was 999%"]}]}'
    detail = tool.publish_sprint_report("PADI", report)
    assert "Published to Spin" in detail
    assert captured["slug"] == "padi-sprint-1-report"
    html = captured["html"]
    assert '<div class="num">81%</div>' in html  # real Jira-derived velocity
    assert '<div class="num">999%</div>' not in html  # agent text can't become a metric
    assert "velocity was 999%" in html  # only appears as a bullet line


def test_guard_skips_already_reported_sprint(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())  # sprint_id=900
    monkeypatch.setattr(tool.store, "get_setting", lambda k, *a, **kw: "900")  # already reported

    published = {"called": False}

    class Pub:
        def publish(self, *a, **k):
            published["called"] = True
            return PublishResult("spin", "https://x", "ok")

    monkeypatch.setattr(tool, "get_publisher", lambda: Pub())
    out = tool.publish_sprint_report("PADI", '{"sections": []}', only_if_new=True)
    assert "Already reported" in out and published["called"] is False


def test_guard_publishes_and_records_new_sprint(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())  # sprint_id=900
    monkeypatch.setattr(tool.store, "get_setting", lambda k, *a, **kw: "880")  # older sprint

    saved = {}
    monkeypatch.setattr(tool.store, "set_setting", lambda k, v, *a, **kw: saved.update({k: v}))

    class Pub:
        def publish(self, *a, **k):
            return PublishResult("spin", "https://x", "Published to Spin: https://x")

    monkeypatch.setattr(tool, "get_publisher", lambda: Pub())
    out = tool.publish_sprint_report("PADI", '{"sections": []}', only_if_new=True)
    assert "Published to Spin" in out
    assert saved.get("sprint_report_last:PADI") == "900"  # marker advanced


def test_failed_delivery_does_not_mark_sprint_reported(monkeypatch):
    """A Slack-draft fallback (Spin not published) must NOT set the reported-marker, or a
    one-off delivery failure would permanently suppress the report on later runs."""
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())

    saved = {}
    monkeypatch.setattr(tool.store, "get_setting", lambda *a, **k: None)
    monkeypatch.setattr(tool.store, "set_setting", lambda k, v, *a, **kw: saved.update({k: v}))

    class DraftPub:
        def publish(self, *a, **k):
            return PublishResult(mode="slack-draft", url=None, detail="Posted a draft.")

    monkeypatch.setattr(tool, "get_publisher", lambda: DraftPub())
    tool.publish_sprint_report("PADI", '{"sections": []}', channel="#padi")
    assert saved == {}  # marker NOT set — a later run can retry


def test_sprint_report_does_not_post_to_slack(monkeypatch):
    """publish_sprint_report must NOT call chat_postMessage — the agent posts the link."""
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())
    monkeypatch.setattr(tool.store, "set_setting", lambda *a, **k: None)

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            return PublishResult(mode="spin", url="https://x", detail="Published to Spin: https://x")

    monkeypatch.setattr(tool, "get_publisher", lambda: FakePub())

    import slack_sdk

    def _boom(token=None):
        raise AssertionError("WebClient must not be instantiated — tool must not post to Slack")

    monkeypatch.setattr(slack_sdk, "WebClient", _boom)
    detail = tool.publish_sprint_report(
        "PADI", '{"sections": []}', channel="#padi", thread_ts="1.2", broadcast=True
    )
    assert "Published to Spin" in detail


def test_get_sprint_history_lists_recent_sprints(monkeypatch):
    import bott.skills.sprint_report.tool as t
    monkeypatch.setattr(t.config, "jira_configured", lambda: True)
    class FakeClient:
        def _sprints(self, board_id, state):
            return [{"id": 1, "name": "Sprint 1"}, {"id": 2, "name": "Sprint 2"}, {"id": 3, "name": "Sprint 3"}]
        def sprint_issues(self, sid):
            return [{"is_done": True, "summary": "x"}]
    eng = t.Engagement(client=FakeClient(), board_id=10, project_key="PADI", title="PADI",
                       client_name="PADI", org="Axelerant", slug_tmpl="s", board_url="")
    monkeypatch.setattr(t, "_resolve_engagement", lambda q: eng)
    out = t.get_sprint_history("PADI", n=2)
    assert "Sprint 3" in out and "Sprint 2" in out and "Sprint 1" not in out  # last 2 by id desc


def test_sprint_report_posts_in_thread(monkeypatch):
    import inspect

    import bott.skills.sprint_report.tool as t

    sig = inspect.signature(t.publish_sprint_report)
    assert "thread_ts" in sig.parameters and "broadcast" in sig.parameters


def test_publish_falls_back_to_slack_on_spin_failure(monkeypatch):
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_resolve_engagement", lambda q: _eng())
    monkeypatch.setattr(tool, "_build_dossier", lambda e: _dossier())
    monkeypatch.setattr(tool.store, "set_setting", lambda *a, **k: None)

    class Boom:
        def publish(self, *a, **k):
            raise RuntimeError("spin down")

    monkeypatch.setattr(tool, "get_publisher", lambda: Boom())

    calls = {}

    def fake_fallback_publish(self, slug, title, html, channel=""):
        calls["channel"] = channel
        return PublishResult(mode="slack-draft", url=None, detail="Posted the report draft to #padi.")

    monkeypatch.setattr(
        "bott.shared.integrations.spin.SlackDraftPublisher.publish", fake_fallback_publish
    )
    detail = tool.publish_sprint_report("PADI", '{"sections": []}', channel="#padi")
    assert "draft" in detail and calls["channel"] == "#padi"
