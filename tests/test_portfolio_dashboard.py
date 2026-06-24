"""Portfolio risk roll-up: aggregation, render, the publish tool, and App Home wiring."""

from __future__ import annotations

from agno.db.sqlite import SqliteDb

from bott.shared import config
from bott.shared.integrations import spin
from bott.shared.integrations.spin import PublishResult
from bott.skills.portfolio import aggregate, dashboard, tool

_ENGS = [  # Memra's real schema: numeric overall_sentiment + trend_vs_prior
    {"account": "Acme", "engagement_id": "e1", "risk_band": "high", "risk_score": 0.9,
     "overall_sentiment": -0.3, "trend_vs_prior": -0.4},   # declining
    {"account": "Beta", "engagement_id": "e2", "risk_band": "medium", "risk_score": 0.5,
     "overall_sentiment": 0.2, "trend_vs_prior": 0.3},     # improving
    {"account": "Gamma", "engagement_id": "e3", "risk_band": "low", "risk_score": 0.1,
     "overall_sentiment": 0.0, "trend_vs_prior": 0.0},     # flat
]


# --- pure aggregation -----------------------------------------------------------
def test_summarize_counts_and_ranking():
    pf = aggregate.summarize(_ENGS)
    assert (pf.total, pf.high, pf.medium, pf.declining, pf.improving) == (3, 1, 1, 1, 1)
    assert [r.account for r in pf.rows] == ["Acme", "Beta", "Gamma"]  # at-risk first


def test_summarize_counts_low_and_flat():
    pf = aggregate.summarize(_ENGS)
    # 1 high, 1 medium, 1 low; declining/improving 1 each so flat = 3-1-1 = 1.
    assert (pf.low, pf.flat) == (1, 1)


def test_summarize_defensive_fields():
    pf = aggregate.summarize([{"engagement_id": "x"}, "junk", {"name": "Z", "band": "HIGH"}])
    assert pf.total == 2 and pf.high == 1  # 'band' alias + uppercase handled; non-dict skipped


def test_dashboard_is_interactive():
    pf = aggregate.summarize(_ENGS)
    pf.rows[0].vel_stories = 12  # Acme enriched for the velocity chart
    html = dashboard.render_portfolio_dashboard(pf, [], "as of today")
    assert html.startswith("<!DOCTYPE html>")
    assert "cdn.jsdelivr.net/npm/chart.js" in html
    for cid in ('id="riskChart"', 'id="sentChart"', 'id="scatterChart"', 'id="velChart"', 'id="trendChart"'):
        assert cid in html
    # interactive controls + client logic (cross-filter / search / sort)
    assert "searchInput" in html and "data-band" in html and "decliningToggle" in html
    assert "const DATA =" in html and "function refresh" in html
    assert '"engagements"' in html and "Acme" in html and "Beta" in html  # embedded data
    assert '"children"' in html and "acctrow" in html  # expandable account/channel rows
    assert '"history": []' in html  # no weekly snapshots embedded yet


def test_dashboard_embeds_history_series():
    pf = aggregate.summarize(_ENGS)
    hist = [{"date": "2026-06-01", "high": 5, "medium": 8, "avg_sentiment": -0.1},
            {"date": "2026-06-08", "high": 4, "medium": 9, "avg_sentiment": 0.05}]
    html = dashboard.render_portfolio_dashboard(pf, hist, "as of today")
    assert "2026-06-01" in html and "2026-06-08" in html  # the series is embedded for the trend line


# --- the publish tool -----------------------------------------------------------
def test_publish_requires_memra(monkeypatch):
    monkeypatch.setattr(config, "memra_configured", lambda: False)
    assert "Memra isn't configured" in tool.publish_portfolio_dashboard()


def test_publish_builds_dashboard_and_returns_link(monkeypatch):
    monkeypatch.setattr(config, "memra_configured", lambda: True)
    monkeypatch.setattr(config, "jira_configured", lambda: False)  # skip enrichment → velocity '—'
    monkeypatch.setattr(tool, "_engagements", lambda: _ENGS)

    captured = {}

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            captured.update(slug=slug, html=html, title=title)
            return PublishResult("spin", "https://x.public.spin.axelerant.tech/", "Published to Spin: https://x...")

    monkeypatch.setattr(tool.history, "record_snapshot", lambda *a, **k: [])  # no real DB write
    monkeypatch.setattr(spin, "get_publisher", lambda: FakePub())
    out = tool.publish_portfolio_dashboard(channel="#leads", top_n=2)
    assert "Published to Spin" in out
    assert captured["slug"] == "bott-portfolio-risk-rollup"
    html = captured["html"]
    assert "chart.js" in html and 'id="riskChart"' in html and "searchInput" in html  # interactive
    assert '"engagements"' in html and "Acme" in html and "Beta" in html  # embedded live data


def test_publish_posts_in_thread_and_broadcasts(monkeypatch):
    """Ad-hoc: the tool posts the link itself in the thread AND broadcasts to the channel
    (Slack 'Also send to channel'), so it works from any channel without naming one."""
    monkeypatch.setattr(config, "memra_configured", lambda: True)
    monkeypatch.setattr(config, "jira_configured", lambda: False)
    monkeypatch.setattr(tool, "_engagements", lambda: _ENGS)
    monkeypatch.setattr(tool.history, "record_snapshot", lambda *a, **k: [])
    monkeypatch.setattr(spin, "get_publisher",
                        lambda: type("P", (), {"publish": lambda s, *a, **k: PublishResult(
                            "spin", "https://x.public.spin.axelerant.tech/", "Published to Spin: …")})())
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    posted = {}

    import slack_sdk
    monkeypatch.setattr(slack_sdk, "WebClient",
                        lambda token=None: type("W", (), {"chat_postMessage": lambda s, **k: posted.update(k)})())
    tool.publish_portfolio_dashboard(channel="C1", thread_ts="1782.45", broadcast=True)
    assert posted["channel"] == "C1" and posted["thread_ts"] == "1782.45"
    assert posted["reply_broadcast"] is True
    assert "x.public.spin.axelerant.tech" in posted["text"]


def test_summarize_rolls_up_to_account_worst_risk_weighted_sentiment_children():
    engs = [
        {"account": "PADI", "engagement_id": "e1", "risk_band": "low", "risk_score": 0.1,
         "overall_sentiment": 0.4, "trend_vs_prior": 0.3, "recent_message_count": 100},
        {"account": "PADI", "engagement_id": "e2", "risk_band": "high", "risk_score": 0.8,
         "overall_sentiment": -0.2, "trend_vs_prior": -0.1, "recent_message_count": 900},
    ]
    pf = aggregate.summarize(engs)
    assert pf.total == 1 and pf.high == 1  # one PADI account, worst band = high
    r = pf.rows[0]
    assert r.account == "PADI" and r.band == "high" and r.score == 0.8  # worst-case
    assert r.detail == "2 engagements"
    assert r.sentiment == -0.2  # worst (lowest) channel sentiment, not the average
    assert len(r.children) == 2 and {c["engagement_id"] for c in r.children} == {"e1", "e2"}


def test_resolve_children_sets_channel_names(monkeypatch):
    """Drill-down children get resolved Slack channel names (fallback to id when unresolved)."""
    from bott.skills.portfolio.aggregate import PortfolioRow
    row = PortfolioRow("PADI", "", "high", 0.8, -0.1, -0.1, detail="2 engagements",
                       children=[{"engagement_id": "e1", "channel": "", "band": "high", "sentiment": -0.2, "trend": -0.1},
                                 {"engagement_id": "e2", "channel": "", "band": "low", "sentiment": 0.4, "trend": 0.3}])
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    chan, name = {"e1": "C1", "e2": "C2"}, {"C1": "padi-fe", "C2": "padi-be"}
    import bott.shared.context as ctx
    monkeypatch.setattr(ctx, "MemraClient",
                        lambda: type("M", (), {"get_entity": lambda s, eid, t: {"record": {"slack_channel_id": chan[eid]}}})())
    import slack_sdk
    monkeypatch.setattr(slack_sdk, "WebClient",
                        lambda token=None: type("W", (), {"conversations_info": lambda s, channel: {"channel": {"name": name[channel]}}})())
    tool._resolve_children([row])
    assert row.children[0]["channel"] == "#padi-fe" and row.children[1]["channel"] == "#padi-be"


def test_history_round_trip(monkeypatch):
    from bott.shared.persistence import store
    from bott.skills.portfolio import history
    kv: dict = {}
    monkeypatch.setattr(store, "get_setting", lambda k, *a, **kw: kv.get(k))
    monkeypatch.setattr(store, "set_setting", lambda k, v, *a, **kw: kv.__setitem__(k, v))
    history.record_snapshot("2026-06-01", {"high": 5, "medium": 8, "avg_sentiment": -0.1})
    history.record_snapshot("2026-06-08", {"high": 4, "medium": 9, "avg_sentiment": 0.0})
    history.record_snapshot("2026-06-08", {"high": 3, "medium": 9, "avg_sentiment": 0.1})  # upsert
    h = history.load_history()
    assert [p["date"] for p in h] == ["2026-06-01", "2026-06-08"]  # deduped, sorted
    assert h[-1]["high"] == 3  # upserted in place


# --- scheduling -----------------------------------------------------------------
def test_create_portfolio_dashboard_scope(tmp_path):
    from bott.skills import scheduling
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_portfolio_dashboard(db, channel="#leads", cron="0 9 * * 1")
    p = sch.payload if hasattr(sch, "payload") else sch.get("payload")
    assert p["user_id"] == "portfolio:risk-rollup" and p["session_id"] == "portfolio-dashboard"
    assert "publish_portfolio_dashboard" in p["message"]
    assert getattr(sch, "name", "") == "portfolio-dashboard:risk-rollup"


# --- App Home -------------------------------------------------------------------
def test_app_home_portfolio_wiring(monkeypatch, tmp_path):
    from bott.interfaces.slack_home import blocks, router, service
    assert "add_portfolio" in str(blocks.build_home_view([]))
    assert blocks.build_portfolio_modal()["callback_id"] == "create_portfolio"

    captured = {}
    monkeypatch.setattr(service, "create_portfolio",
                        lambda db, channel, frequency, time_str: captured.update(
                            channel=channel, frequency=frequency, time=time_str))
    router._submit_portfolio(None, {
        "channel": {"v": {"selected_channel": "C9"}},
        "frequency": {"v": {"selected_option": {"value": "weekly"}}},
        "time": {"v": {"selected_time": "09:00"}}})
    assert captured == {"channel": "C9", "frequency": "weekly", "time": "09:00"}

    from bott.skills import scheduling
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    scheduling.create_portfolio_dashboard(db, channel="C9", cron="0 9 * * 1")  # real creator (service is patched)
    assert any(r["icon"] == "🗂️" for r in service.list_rows(db))
