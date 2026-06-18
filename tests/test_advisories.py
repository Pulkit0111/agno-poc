"""Drupal security-advisory parsing + digest rendering (no network in tests)."""

from __future__ import annotations

from bott.skills import advisories

NOW = 1781760000  # ~2026-06-18

RAW = [
    {
        "title": "Plotly.js Graphing - Critical - PHP object injection - SA-CONTRIB-2026-050",
        "url": "https://www.drupal.org/sa-contrib-2026-050",
        "field_sa_cve": ["CVE-2026-55810"],
        "field_sa_type": "PHP object injection",
        "field_sa_description": {"value": "<p>The module stores PHP-serialized data. "
                                          "Malicious data triggers object injection on unserialize.</p>"},
        "field_sa_solution": {"value": "<p>Upgrade to plotly_js-3.0.2.</p>"},
        "created": NOW - 3600,
    },
    {
        "title": "Drupal core - Less critical - Cache poisoning and open redirect - SA-CORE-2026-007",
        "url": "https://www.drupal.org/sa-core-2026-007",
        "field_sa_cve": ["CVE-2026-55806"],
        "field_sa_description": {"value": "rebuild.php fails to validate the Host header."},
        "field_sa_solution": {"value": "Upgrade to Drupal 11.3.12."},
        "created": NOW - 7200,
    },
    {  # outside the window — must be filtered out
        "title": "Old Module - Critical - SQL injection - SA-CONTRIB-2020-001",
        "url": "https://www.drupal.org/sa-contrib-2020-001",
        "field_sa_cve": [],
        "created": NOW - 100 * 86400,
    },
]


def test_parse_filters_window_and_sorts_by_severity():
    out = advisories.parse_advisories(RAW, NOW, window_days=2)
    assert len(out) == 2  # the 2020 one is outside the window
    # Critical sorts before Less critical.
    assert out[0]["sa_id"] == "SA-CONTRIB-2026-050"
    assert out[0]["severity"] == "Critical" and out[0]["icon"] == "🔴"
    assert out[0]["project"] == "Plotly.js Graphing"
    assert out[0]["cve"] == "CVE-2026-55810"
    assert "plotly_js-3.0.2" in out[0]["fix"]
    assert out[1]["sa_id"] == "SA-CORE-2026-007"
    assert out[1]["icon"] == "🟡"


def test_render_digest_format():
    out = advisories.render_digest(advisories.parse_advisories(RAW, NOW, window_days=2))
    assert out.startswith("🔒 *Drupal Security Advisories —")
    assert "1 Critical" in out and "1 Less critical" in out
    assert "✅ Fix:" in out
    # Advisory ID is a labeled link (no bare URL → nothing for Slack to unfurl).
    assert "<https://www.drupal.org/sa-contrib-2026-050|SA-CONTRIB-2026-050>" in out
    assert "🔗 https://" not in out


def test_fix_summary_extracts_versions():
    assert advisories._fix_summary(
        "If you use the Plotly.js Graphing module for Drupal, upgrade to plotly_js-3.0.2 ."
    ) == "plotly_js-3.0.2"
    core = ("Install the latest version: Drupal 11 If you use Drupal 11.3.x, update to "
            "Drupal 11.3.12 . If you use Drupal 11.2.x, update to Drupal 11.2.14 .")
    assert advisories._fix_summary(core) == "Drupal 11.3.12 / 11.2.14"


def test_render_empty():
    assert "no new advisories" in advisories.render_digest([]).lower()


def test_tool_uses_feed_and_renders(monkeypatch):
    monkeypatch.setattr(advisories, "_fetch_raw", lambda *a, **k: RAW)
    monkeypatch.setattr(advisories.time, "time", lambda: NOW + 100)
    out = advisories.drupal_security_advisories(window_days=2)
    assert "Drupal Security Advisories" in out
    assert "SA-CONTRIB-2026-050" in out


def test_post_tool_disables_unfurl(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(advisories, "_fetch_raw", lambda *a, **k: RAW)
    monkeypatch.setattr(advisories.time, "time", lambda: NOW + 100)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr("slack_sdk.WebClient.chat_postMessage",
                        lambda self, **kw: captured.update(kw))
    out = advisories.post_drupal_security_advisories("C123", window_days=2)
    assert captured["channel"] == "C123"
    assert captured["unfurl_links"] is False and captured["unfurl_media"] is False
    assert "SA-CONTRIB-2026-050" in captured["text"]
    assert "Posted" in out


def test_tool_handles_fetch_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(advisories, "_fetch_raw", boom)
    out = advisories.drupal_security_advisories()
    assert "Couldn't fetch" in out
