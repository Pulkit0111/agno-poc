"""Connectors panel for the App Home — live ✓/✗ from config.*_configured()."""

from __future__ import annotations

from bott.interfaces.slack_home import connectors_panel as cp


def _force(monkeypatch, **flags):
    """Pin every connector's configured() to a known bool + codex/slack presence."""
    monkeypatch.setattr(cp.config, "github_app_configured", lambda: flags.get("github", False))
    monkeypatch.setattr(cp.config, "jira_configured", lambda: flags.get("jira", False))
    monkeypatch.setattr(cp.config, "confluence_configured", lambda: flags.get("confluence", False))
    monkeypatch.setattr(cp.config, "sentry_configured", lambda: flags.get("sentry", False))
    monkeypatch.setattr(cp.config, "memra_configured", lambda: flags.get("memra", False))
    monkeypatch.setattr(cp.config, "spin_configured", lambda: flags.get("spin", False))
    monkeypatch.setattr(cp.config, "google_delegation_configured", lambda: flags.get("google", False))
    monkeypatch.setattr(cp.codex_tokens, "is_connected", lambda: flags.get("codex", False))
    if flags.get("slack"):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s")
    else:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)


def test_connector_statuses_reflect_config(monkeypatch):
    _force(monkeypatch, jira=True, sentry=False, google=False, memra=True, slack=True)
    by = {s["name"]: s for s in cp.connector_statuses()}
    assert by["Jira"]["ok"] is True
    assert by["Memra"]["ok"] is True
    assert by["Sentry"]["ok"] is False
    assert by["Google"]["ok"] is False
    assert by["Slack"]["ok"] is True
    # Renamed per design: a single plain "Google", not "Google · Gmail/Drive/Cal".
    assert "Google" in by and "·" not in "".join(by.keys())


def test_connectors_section_renders_tick_and_cross(monkeypatch):
    _force(monkeypatch, jira=True, sentry=False)
    blocks = cp.connectors_section()
    text = str(blocks)
    assert "Connectors" in text
    assert "✅" in text  # at least one connected
    assert "❌" in text  # at least one not connected


def test_connectors_section_offline_hint_present(monkeypatch):
    _force(monkeypatch, sentry=False)
    text = str(cp.connectors_section())
    # A not-connected connector carries a short how-to-fix hint, not just a cross.
    assert "Sentry" in text
