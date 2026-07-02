# src/bott/interfaces/slack_home/quick_actions.py
"""Quick-action runners for the App Home.

The self-contained, no-argument actions (security digest, PR-review trends, portfolio risk)
run their existing tool impl and return text that the router DMs back to the caller. The
engagement-scoped actions (Ask, Sprint) need input, so they're handled via a modal in the
router — ``run_quick_action`` returns None for those.
"""

from __future__ import annotations

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.slack_home.quick_actions")


def run_quick_action(action_id: str) -> str | None:
    """Run a no-argument quick action and return the text to DM. Returns None when the
    action isn't a no-arg runner (i.e. it needs a modal). Never raises."""
    try:
        if action_id == "qa_security":
            from bott.skills.advisories import drupal_security_advisories
            return drupal_security_advisories()
        if action_id == "qa_pr_trends":
            from bott.skills.review_trends import review_trends_impl
            return review_trends_impl(30)
        if action_id == "qa_portfolio":
            from bott.skills.portfolio.tool import get_portfolio_risk_data
            return get_portfolio_risk_data()
    except Exception as e:  # noqa: BLE001 — a quick action must degrade to a message, not crash
        log.error("quick action %s failed: %s", action_id, e)
        return f"Couldn't run that just now — {e}"
    return None
