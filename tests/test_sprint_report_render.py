"""Pure rendering + metrics for the sprint report (no I/O)."""

from __future__ import annotations

from bott.skills.sprint_report import render
from bott.skills.sprint_report.render import Metrics, Narrative, ReportMeta


def _issue(points, done, has_points=True, summary="s", tag=None):
    return {"summary": summary, "points": points, "is_done": done,
            "has_points": has_points, "tag": tag, "status": "Done" if done else "To Do"}


def test_compute_metrics_points_velocity_and_delivered():
    issues = [_issue(5, True), _issue(3, True), _issue(8, False)]
    m = render.compute_metrics(issues)
    assert m.stories_delivered == 2
    assert m.points_planned == 16
    assert m.points_achieved == 8
    assert m.velocity_pct == 50
    assert m.has_points is True


def test_compute_metrics_no_points_tracked():
    issues = [_issue(0, True, has_points=False), _issue(0, False, has_points=False)]
    m = render.compute_metrics(issues)
    assert m.has_points is False
    assert m.velocity_pct is None  # no planned points -> no velocity


def test_sprint_number_and_period_and_h1():
    assert render.sprint_number("PADI Sprint 7") == 7
    assert render.sprint_number("Backlog") is None
    assert render.format_period("2026-06-01T00:00:00.000Z", "2026-06-12T00:00:00.000Z") == \
        "1 June – 12 June 2026"
    assert render._h1("PADI Digital Overhaul") == "PADI <span>Digital Overhaul</span>"


def _meta():
    return ReportMeta(title="PADI Digital Overhaul", client="PADI", org="Axelerant",
                      sprint_label="Sprint 1", next_sprint_label="Sprint 2",
                      period="1 June – 12 June 2026")


def test_render_html_carries_metrics_and_sections():
    metrics = Metrics(stories_delivered=13, points_planned=75, points_achieved=61,
                      velocity_pct=81, has_points=True)
    done = [{"summary": "Decoupled Frontend Scaffold"}]
    nxt = [{"summary": "JSON API Setup", "tag": "spike"}]
    narrative = Narrative(
        highlights=["Ceremonies running smoothly"],
        risks=[{"issue": "Acquia perms", "impact": "4-5 tickets blocked", "status": "resolved"}],
        actions=[{"title": "Begin UAT", "desc": "Validate stories",
                  "link": "https://axelerant.atlassian.net/x", "owner": "PADI Team",
                  "priority": "high"}],
        priorities_note="Spikes de-risk Sprint 2.",
    )
    html = render.render_html(_meta(), metrics, done, nxt, narrative)

    # Exact headline numbers in the stat cards.
    for num, label in [("13", "Stories Delivered"), ("75", "Story Points Planned"),
                       ("61", "Story Points Achieved"), ("81%", "Target Velocity")]:
        assert f'<div class="num">{num}</div>' in html
        assert label in html
    # Deterministic story content.
    assert "Decoupled Frontend Scaffold" in html
    assert "JSON API Setup" in html and 'class="story-type-spike"' in html
    # Narrative sections.
    assert "Ceremonies running smoothly" in html
    assert "Acquia perms" in html and 'class="status-resolved"' in html
    assert "Begin UAT" in html and "axelerant.atlassian.net/x" in html
    assert "Actions Needed from PADI" in html
    assert "self-contained" not in html  # sanity: not a placeholder
    assert html.strip().startswith("<!DOCTYPE html>")


def test_render_escapes_narrative_xss():
    metrics = Metrics(0, 0, 0, None, has_points=False)
    narrative = Narrative(highlights=["<script>alert(1)</script>"])
    html = render.render_html(_meta(), metrics, [], [], narrative)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_missing_optional_sections_omitted_not_broken():
    metrics = Metrics(1, 5, 5, 100, has_points=True)
    html = render.render_html(_meta(), metrics, [{"summary": "x"}], [], Narrative())
    # No risks/actions/priorities supplied -> those sections simply absent.
    assert "Risks &amp; Blockers" not in html and "Risks & Blockers" not in html
    assert "Actions Needed" not in html
    assert "Achievements This Sprint" in html  # always present
