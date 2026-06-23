"""Pure rendering + metrics for the sprint report (no I/O) — block-based body."""

from __future__ import annotations

from bott.skills.sprint_report import render
from bott.skills.sprint_report.render import Metrics, ReportMeta


def _issue(points, done, has_points=True, summary="s", tag=None):
    return {"summary": summary, "points": points, "is_done": done, "has_points": has_points,
            "tag": tag, "status": "Done" if done else "To Do"}


def test_compute_metrics_points_velocity_and_delivered():
    m = render.compute_metrics([_issue(5, True), _issue(3, True), _issue(8, False)])
    assert (m.stories_delivered, m.points_planned, m.points_achieved, m.velocity_pct) == (2, 16, 8, 50)
    assert m.has_points is True


def test_compute_metrics_no_points_tracked():
    m = render.compute_metrics([_issue(0, True, has_points=False), _issue(0, False, has_points=False)])
    assert m.has_points is False and m.velocity_pct is None


def test_helpers():
    assert render.sprint_number("PADI Sprint 7") == 7
    assert render.sprint_number("Backlog") is None
    assert render.format_period("2026-06-01T00:00:00Z", "2026-06-12T00:00:00Z") == "1 June – 12 June 2026"
    assert render._h1("PADI Digital Overhaul") == "PADI <span>Digital Overhaul</span>"


def _meta():
    return ReportMeta("PADI Digital Overhaul", "PADI", "Axelerant", "Sprint 1", "Sprint 2",
                      "1 June – 12 June 2026")


def test_header_shows_metrics_and_omits_points_when_untracked():
    with_pts = render.render_header(_meta(), Metrics(13, 75, 61, 81, has_points=True))
    for num in ("13", "75", "61", "81%"):
        assert f'<div class="num">{num}</div>' in with_pts
    no_pts = render.render_header(_meta(), Metrics(13, 0, 0, None, has_points=False))
    assert '<div class="num">13</div>' in no_pts and "Story Points Planned" not in no_pts


def test_render_report_dynamic_blocks_and_sources():
    metrics = Metrics(13, 75, 61, 81, has_points=True)
    sources = {
        "delivered_stories": [{"summary": "Frontend scaffold", "status": "Done"}],
        "next_sprint_stories": [{"summary": "JSON API", "tag": "spike"}],
        "incomplete": [{"summary": "Acquia perms", "status": "Blocked"}],
    }
    sections = [
        {"type": "bullets", "title": "Highlights", "items": ["Ceremonies on cadence"]},
        {"type": "table", "title": "Delivered", "source": "delivered_stories"},
        {"type": "table", "title": "Risks", "columns": ["Issue", "Impact", "Status"],
         "rows": [["Acquia perms", "Blocked tickets", {"badge": "resolved"}]]},
        {"type": "cards", "title": "Next sprint", "source": "next_sprint_stories"},
        {"type": "actions", "title": "Actions", "items": [
            {"title": "Begin UAT", "desc": "Validate", "link": "https://axelerant.atlassian.net/x",
             "owner": "PADI", "priority": "high"}]},
        {"type": "callout", "text": "Spikes de-risk Sprint 2."},
        {"type": "nonsense"},  # unknown -> skipped, no crash
    ]
    html = render.render_report(_meta(), metrics, sources, sections)
    assert html.startswith("<!DOCTYPE html>")
    assert "Ceremonies on cadence" in html
    assert "Frontend scaffold" in html and 'class="done-badge"' in html  # source table
    assert "Acquia perms" in html and 'class="status-resolved"' in html  # agent table + badge
    assert "JSON API" in html and 'class="story-type-spike"' in html  # cards from source
    assert "Begin UAT" in html and "axelerant.atlassian.net/x" in html
    assert "Spikes de-risk Sprint 2." in html
    assert "nonsense" not in html  # unknown block dropped


def test_render_escapes_agent_text():
    html = render.render_report(_meta(), Metrics(0, 0, 0, None, False), {},
                                [{"type": "bullets", "items": ["<script>alert(1)</script>"]}])
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
