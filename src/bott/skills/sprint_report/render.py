"""Pure rendering for the sprint report — metrics computation + HTML assembly.

No I/O: every function here takes plain data and returns strings, so it's fully
unit-testable. All model-supplied narrative text is HTML-escaped before it touches the
template (the renderer owns the markup; the agent only supplies words)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime

from bott.skills.sprint_report import template


# --------------------------------------------------------------------------- types
@dataclass
class Metrics:
    stories_delivered: int
    points_planned: float
    points_achieved: float
    velocity_pct: int | None
    has_points: bool


@dataclass
class ReportMeta:
    title: str  # e.g. "PADI Digital Overhaul" — first word plain, rest accent-coloured
    client: str
    org: str
    sprint_label: str  # "Sprint 1"
    next_sprint_label: str  # "Sprint 2"
    period: str  # "1 June – 12 June 2026"


@dataclass
class Narrative:
    """The agent-authored sections. Everything else on the page is deterministic."""

    highlights: list[str] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)  # {issue, impact, status}
    actions: list[dict] = field(default_factory=list)  # {title, desc, link?, owner?, priority}
    priorities_note: str = ""


# ----------------------------------------------------------------------- pure utils
def _esc(s: object) -> str:
    return html.escape(str(s or ""))


def _num(x: float) -> str:
    """Drop a trailing .0 so 61.0 -> '61' but 6.5 -> '6.5'."""
    return str(int(x)) if float(x).is_integer() else str(x)


def sprint_number(name: str) -> int | None:
    """Pull the trailing sprint number out of a Jira sprint name ('PADI Sprint 3' -> 3)."""
    m = re.search(r"(\d+)\s*$", name or "")
    return int(m.group(1)) if m else None


def format_period(start_iso: str | None, end_iso: str | None) -> str:
    """'2026-06-01T..' + '2026-06-12T..' -> '1 June – 12 June 2026'. Best-effort; returns
    '' if dates are missing/unparseable."""
    def _d(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            return None

    a, b = _d(start_iso), _d(end_iso)
    if a and b:
        if a.year == b.year:
            return f"{a.day} {a.strftime('%B')} – {b.day} {b.strftime('%B')} {b.year}"
        return f"{a.day} {a.strftime('%B %Y')} – {b.day} {b.strftime('%B %Y')}"
    one = a or b
    return f"{one.day} {one.strftime('%B %Y')}" if one else ""


def compute_metrics(issues: list[dict]) -> Metrics:
    """Headline numbers from normalized Jira issues. 'Delivered' / 'achieved' use the
    Jira *done* status category; planned points = all issues in the sprint."""
    planned = sum(float(i.get("points") or 0) for i in issues)
    achieved = sum(float(i.get("points") or 0) for i in issues if i.get("is_done"))
    delivered = sum(1 for i in issues if i.get("is_done"))
    has_points = any(i.get("has_points") for i in issues)
    velocity = round(achieved / planned * 100) if planned > 0 else None
    return Metrics(
        stories_delivered=delivered,
        points_planned=planned,
        points_achieved=achieved,
        velocity_pct=velocity,
        has_points=has_points,
    )


# ------------------------------------------------------------------ section builders
def _h1(title: str) -> str:
    """First word plain, the rest accent-coloured (matches the reference header)."""
    parts = (title or "").split(" ", 1)
    if len(parts) == 1:
        return _esc(parts[0])
    return f"{_esc(parts[0])} <span>{_esc(parts[1])}</span>"


def _stat_card(num: str, label: str) -> str:
    return f'<div class="stat-card"><div class="num">{_esc(num)}</div><div class="label">{_esc(label)}</div></div>'


def render_header(meta: ReportMeta, metrics: Metrics) -> str:
    pts_planned = _num(metrics.points_planned) if metrics.has_points else "—"
    pts_achieved = _num(metrics.points_achieved) if metrics.has_points else "—"
    velocity = f"{metrics.velocity_pct}%" if metrics.velocity_pct is not None else "—"
    cards = "".join([
        _stat_card(str(metrics.stories_delivered), "Stories Delivered"),
        _stat_card(pts_planned, "Story Points Planned"),
        _stat_card(pts_achieved, "Story Points Achieved"),
        _stat_card(velocity, "Target Velocity"),
    ])
    meta_line = f"{_esc(meta.org)} × {_esc(meta.client)} &nbsp;·&nbsp; {_esc(meta.sprint_label)} Period: {_esc(meta.period)}"
    return (
        '<div class="header"><div class="header-inner">'
        f'<div class="header-top"><div class="logo">{_esc(meta.org)}</div>'
        f'<div class="sprint-badge">{_esc(meta.sprint_label)} Report</div></div>'
        f"<h1>{_h1(meta.title)}</h1>"
        f'<div class="header-meta">{meta_line}</div>'
        f'<div class="header-stats">{cards}</div>'
        "</div></div>" + template.CURVE_DIVIDER
    )


def _section(title: str, inner: str) -> str:
    return (
        f'<div class="section"><div class="section-label"><div class="dot"></div>'
        f"<h2>{_esc(title)}</h2></div>{inner}</div>"
    )


def render_achievements(done_issues: list[dict], highlights: list[str]) -> str:
    rows = "".join(
        f"<tr><td>{n}</td><td>{_esc(i.get('summary'))}</td>"
        f'<td><span class="done-badge">Done</span></td></tr>'
        for n, i in enumerate(done_issues, 1)
    ) or '<tr><td>—</td><td>No stories completed this sprint.</td><td></td></tr>'
    table = (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Story</th><th>Status</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )
    hl = ""
    if highlights:
        items = "".join(f'<div class="highlight-item">{_esc(h)}</div>' for h in highlights)
        hl = f'<div class="highlights" style="margin-top:16px;">{items}</div>'
    return _section("Achievements This Sprint", table + hl)


_RISK_STATUS = {
    "resolved": ("status-resolved", "Resolved"),
    "monitored": ("status-monitored", "Monitored"),
    "inprogress": ("status-inprogress", "In Progress"),
}


def render_risks(risks: list[dict]) -> str:
    if not risks:
        return ""
    rows = []
    for n, r in enumerate(risks, 1):
        cls, label = _RISK_STATUS.get(str(r.get("status", "")).lower().replace(" ", ""),
                                      ("status-monitored", "Monitored"))
        rows.append(
            f"<tr><td>{n}</td>"
            f'<td style="font-weight:600;color:#0D1B2A;font-size:13px;">{_esc(r.get("issue"))}</td>'
            f'<td><span class="impact-text">{_esc(r.get("impact"))}</span></td>'
            f'<td><span class="{cls}">{label}</span></td></tr>'
        )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Issue</th><th>Impact</th>'
        f"<th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )
    return _section("Risks & Blockers", table)


def _story_tag(tag: str | None) -> str:
    if tag == "spike":
        return '<span class="story-type-spike">Spike</span> '
    if tag == "poc":
        return '<span class="story-type-poc">POC</span> '
    return ""


def render_priorities(next_issues: list[dict], label: str, note: str) -> str:
    if not next_issues:
        return ""
    cards = "".join(
        f'<div class="story-card"><div class="story-num">{n:02d}</div>'
        f'<div class="story-title">{_story_tag(i.get("tag"))}{_esc(i.get("summary"))}</div></div>'
        for n, i in enumerate(next_issues, 1)
    )
    grid = f'<div class="stories-grid">{cards}</div>'
    callout = f'<div class="callout">{_esc(note)}</div>' if note else ""
    return _section(f"{label} Priorities", grid + callout)


def render_actions(actions: list[dict], client: str = "") -> str:
    if not actions:
        return ""
    cards = []
    for a in actions:
        prio = "high" if str(a.get("priority", "")).lower() == "high" else "medium"
        link = ""
        url = str(a.get("link") or "")
        if url.startswith("http://") or url.startswith("https://"):
            link = f'<a class="action-link" href="{_esc(url)}" target="_blank">Open link →</a>'
        owner = (
            f'<span class="action-owner">{_esc(a.get("owner"))}</span>' if a.get("owner") else ""
        )
        prio_label = "High Priority" if prio == "high" else "Medium Priority"
        cards.append(
            f'<div class="action-card"><div class="priority-dot priority-{prio}"></div>'
            f'<div class="action-content">'
            f'<div class="action-title">{_esc(a.get("title"))}</div>'
            f'<div class="action-desc">{_esc(a.get("desc"))}</div>'
            f"{link}"
            f'<div class="action-meta">{owner}'
            f'<span class="priority-tag {prio}">{prio_label}</span></div>'
            "</div></div>"
        )
    title = f"Actions Needed from {client}" if client else "Actions Needed"
    return _section(title, f'<div class="actions-list">{"".join(cards)}</div>')


def render_footer(meta: ReportMeta) -> str:
    return (
        '<div class="footer"><div class="footer-inner">'
        f'<div><div class="footer-logo">{_esc(meta.org)}</div></div>'
        f'<div class="footer-note">{_esc(meta.client)} · {_esc(meta.sprint_label)}<br>{_esc(meta.period)}</div>'
        "</div></div>"
    )


def render_html(
    meta: ReportMeta,
    metrics: Metrics,
    done_issues: list[dict],
    next_issues: list[dict],
    narrative: Narrative,
) -> str:
    """Assemble the full self-contained HTML page."""
    body = "".join([
        render_header(meta, metrics),
        '<div class="main">',
        render_achievements(done_issues, narrative.highlights),
        render_risks(narrative.risks),
        render_priorities(next_issues, meta.next_sprint_label, narrative.priorities_note),
        render_actions(narrative.actions, meta.client),
        "</div>",
        render_footer(meta),
    ])
    title = f"{meta.title} — {meta.sprint_label} Report"
    return template.page(title, body)
