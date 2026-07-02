"""Quick-action runners for the App Home — self-contained tool calls, DM'd back."""

from __future__ import annotations

from bott.interfaces.slack_home import quick_actions as qa


def test_run_quick_action_security(monkeypatch):
    import bott.skills.advisories as adv
    monkeypatch.setattr(adv, "drupal_security_advisories", lambda *a, **k: "ADVISORY TEXT")
    assert "ADVISORY TEXT" in qa.run_quick_action("qa_security")


def test_run_quick_action_pr_trends(monkeypatch):
    import bott.skills.review_trends as rt
    monkeypatch.setattr(rt, "review_trends_impl", lambda days=30: f"TRENDS {days}d")
    assert "TRENDS 30d" in qa.run_quick_action("qa_pr_trends")


def test_run_quick_action_portfolio(monkeypatch):
    import bott.skills.portfolio.tool as pt
    monkeypatch.setattr(pt, "get_portfolio_risk_data", lambda: "PORTFOLIO RISK")
    assert "PORTFOLIO RISK" in qa.run_quick_action("qa_portfolio")


def test_unknown_action_returns_none():
    # qa_ask / qa_sprint need an argument (modal), so they are NOT no-arg runners.
    assert qa.run_quick_action("qa_ask") is None
    assert qa.run_quick_action("nope") is None


def test_failure_is_caught_not_raised(monkeypatch):
    import bott.skills.review_trends as rt

    def boom(days=30):
        raise RuntimeError("db down")

    monkeypatch.setattr(rt, "review_trends_impl", boom)
    out = qa.run_quick_action("qa_pr_trends")
    assert "couldn't" in out.lower()
