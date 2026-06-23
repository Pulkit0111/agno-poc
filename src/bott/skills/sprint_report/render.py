"""Rendering for the sprint report — deterministic metrics + a dynamic, block-based body.

The header (title, sprint, period, stat-cards) is rendered deterministically from Jira so
the numbers are always trustworthy. The BODY is dynamic: the agent composes a list of
*blocks* (chosen per engagement), and each block type has a polished, on-brand renderer
here. The agent never writes HTML — it picks block types and supplies text/data, which is
escaped and laid out by the design system. Pure (no I/O), so fully unit-testable."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
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


# ----------------------------------------------------------------------- pure utils
def _esc(s: object) -> str:
    return html.escape(str(s or ""))


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def sprint_number(name: str) -> int | None:
    m = re.search(r"(\d+)\s*$", name or "")
    return int(m.group(1)) if m else None


def format_period(start_iso: str | None, end_iso: str | None) -> str:
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
    planned = sum(float(i.get("points") or 0) for i in issues)
    achieved = sum(float(i.get("points") or 0) for i in issues if i.get("is_done"))
    delivered = sum(1 for i in issues if i.get("is_done"))
    has_points = any(i.get("has_points") for i in issues)
    velocity = round(achieved / planned * 100) if planned > 0 else None
    return Metrics(delivered, planned, achieved, velocity, has_points)


# ------------------------------------------------------------------ header / chrome
def _h1(title: str) -> str:
    parts = (title or "").split(" ", 1)
    if len(parts) == 1:
        return _esc(parts[0])
    return f"{_esc(parts[0])} <span>{_esc(parts[1])}</span>"


def _stat_card(num: str, label: str) -> str:
    return f'<div class="stat-card"><div class="num">{_esc(num)}</div><div class="label">{_esc(label)}</div></div>'


def render_header(meta: ReportMeta, metrics: Metrics) -> str:
    cards = [_stat_card(str(metrics.stories_delivered), "Stories Delivered")]
    if metrics.has_points:
        cards += [
            _stat_card(_num(metrics.points_planned), "Story Points Planned"),
            _stat_card(_num(metrics.points_achieved), "Story Points Achieved"),
            _stat_card(f"{metrics.velocity_pct}%" if metrics.velocity_pct is not None else "—",
                       "Target Velocity"),
        ]
    meta_line = (f"{_esc(meta.org)} × {_esc(meta.client)} &nbsp;·&nbsp; "
                 f"{_esc(meta.sprint_label)} Period: {_esc(meta.period)}")
    return (
        '<div class="header"><div class="header-inner">'
        f'<div class="header-top"><div class="logo">{_esc(meta.org)}</div>'
        f'<div class="sprint-badge">{_esc(meta.sprint_label)} Report</div></div>'
        f"<h1>{_h1(meta.title)}</h1>"
        f'<div class="header-meta">{meta_line}</div>'
        f'<div class="header-stats">{"".join(cards)}</div>'
        "</div></div>" + template.CURVE_DIVIDER
    )


def render_footer(meta: ReportMeta) -> str:
    return (
        '<div class="footer"><div class="footer-inner">'
        f'<div><div class="footer-logo">{_esc(meta.org)}</div></div>'
        f'<div class="footer-note">{_esc(meta.client)} · {_esc(meta.sprint_label)}<br>{_esc(meta.period)}</div>'
        "</div></div>"
    )


def _section(title: str | None, inner: str) -> str:
    head = ""
    if title:
        head = (f'<div class="section-label"><div class="dot"></div>'
                f"<h2>{_esc(title)}</h2></div>")
    return f'<div class="section">{head}{inner}</div>'


# ----------------------------------------------------------------- block renderers
_STATUS = {
    "resolved": ("status-resolved", "Resolved"), "monitored": ("status-monitored", "Monitored"),
    "inprogress": ("status-inprogress", "In Progress"), "done": ("status-resolved", "Done"),
}


def _badge(tone: str, text: str | None = None) -> str:
    cls, label = _STATUS.get((tone or "").lower().replace(" ", ""), ("status-monitored", tone or ""))
    return f'<span class="{cls}">{_esc(text or label)}</span>'


def _cell(value: object) -> str:
    """A table cell: plain text, or a status badge for {"badge": tone} / {"tone","text"}."""
    if isinstance(value, dict):
        tone = value.get("badge") or value.get("tone") or value.get("status")
        return _badge(str(tone), value.get("text"))
    return _esc(value)


def _stories_rows(issues: list[dict], done_badge: bool) -> str:
    rows = []
    for n, i in enumerate(issues, 1):
        status = ('<span class="done-badge">Done</span>' if done_badge
                  else _esc(i.get("status") or ""))
        rows.append(f"<tr><td>{n}</td><td>{_esc(i.get('summary'))}</td><td>{status}</td></tr>")
    return "".join(rows) or '<tr><td>—</td><td>None.</td><td></td></tr>'


def _table_block(b: dict, sources: dict) -> str:
    src = b.get("source")
    if src in ("delivered_stories", "incomplete"):
        head = "<tr><th>#</th><th>Story</th><th>Status</th></tr>"
        body = _stories_rows(sources.get(src, []), done_badge=(src == "delivered_stories"))
    else:
        cols = b.get("columns") or []
        head = "<tr>" + "".join(f"<th>{_esc(c)}</th>" for c in cols) + "</tr>"
        body = "".join(
            "<tr>" + "".join(f"<td>{_cell(c)}</td>" for c in row) + "</tr>"
            for row in (b.get("rows") or [])
        ) or '<tr><td>—</td></tr>'
    table = f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{body}</tbody></table></div>'
    return _section(b.get("title"), table)


def _cards_block(b: dict, sources: dict) -> str:
    items = sources.get(b["source"]) if b.get("source") else (b.get("items") or [])
    cards = []
    for n, it in enumerate(items, 1):
        summary = it.get("summary") if it.get("summary") is not None else it.get("title")
        tag = it.get("tag")
        tag_html = (f'<span class="story-type-{tag}">{tag.upper()}</span> '
                    if tag in ("spike", "poc") else "")
        cards.append(f'<div class="story-card"><div class="story-num">{n:02d}</div>'
                     f'<div class="story-title">{tag_html}{_esc(summary)}</div></div>')
    grid = f'<div class="stories-grid">{"".join(cards)}</div>' if cards else ""
    return _section(b.get("title"), grid)


def _bullets_block(b: dict, _sources: dict) -> str:
    items = "".join(f'<div class="highlight-item">{_esc(x)}</div>' for x in (b.get("items") or []))
    return _section(b.get("title"), f'<div class="highlights" style="margin-top:4px;">{items}</div>')


def _actions_block(b: dict, _sources: dict) -> str:
    cards = []
    for a in b.get("items") or []:
        prio = "high" if str(a.get("priority", "")).lower() == "high" else "medium"
        url = str(a.get("link") or "")
        link = (f'<a class="action-link" href="{_esc(url)}" target="_blank">Open link →</a>'
                if url.startswith(("http://", "https://")) else "")
        owner = f'<span class="action-owner">{_esc(a.get("owner"))}</span>' if a.get("owner") else ""
        cards.append(
            f'<div class="action-card"><div class="priority-dot priority-{prio}"></div>'
            f'<div class="action-content"><div class="action-title">{_esc(a.get("title"))}</div>'
            f'<div class="action-desc">{_esc(a.get("desc"))}</div>{link}'
            f'<div class="action-meta">{owner}'
            f'<span class="priority-tag {prio}">{"High" if prio == "high" else "Medium"} Priority</span>'
            "</div></div></div>"
        )
    return _section(b.get("title"), f'<div class="actions-list">{"".join(cards)}</div>')


def _callout_block(b: dict, _sources: dict) -> str:
    return f'<div class="section"><div class="callout">{_esc(b.get("text"))}</div></div>'


def _prose_block(b: dict, _sources: dict) -> str:
    paras = b.get("paragraphs") or ([b["text"]] if b.get("text") else [])
    body = "".join(f'<p class="impact-text" style="margin-bottom:10px;">{_esc(p)}</p>' for p in paras)
    return _section(b.get("title"), body)


_BLOCKS = {
    "table": _table_block, "cards": _cards_block, "bullets": _bullets_block,
    "actions": _actions_block, "callout": _callout_block, "prose": _prose_block,
}


def render_report(meta: ReportMeta, metrics: Metrics, sources: dict, sections: list[dict]) -> str:
    """Assemble the page: deterministic header + dynamic agent blocks + footer. Unknown
    block types are skipped (never a broken page)."""
    body = [render_header(meta, metrics), '<div class="main">']
    for b in sections or []:
        if not isinstance(b, dict):
            continue
        fn = _BLOCKS.get(str(b.get("type", "")).lower())
        if fn is not None:
            body.append(fn(b, sources))
    body += ["</div>", render_footer(meta)]
    title = f"{meta.title} — {meta.sprint_label} Report"
    return template.page(title, "".join(body))
