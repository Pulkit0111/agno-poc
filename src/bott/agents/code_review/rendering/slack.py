"""Render a completed review as Slack Block Kit blocks — port of render-slack.ts.

One scannable threaded message: verdict header, summary, (verdict-changed block on
re-reviews), counts, top-3 findings, "what I checked", soft-note/downgrade footer,
and action buttons (View on GitHub, Re-review). Apply-fixes button is deferred.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from bott.shared.mrkdwn import to_mrkdwn

from ..core.models import ReviewOutput
from ..core.types import ToolCallTrace
from ..core.verdict_gate import GateResult

SEVERITY_RANK = {"issue": 0, "suggestion": 1}
SEVERITY_EMOJI = {"issue": "🔴", "suggestion": "🟡"}
VERDICT_PILL = {"approve": "🟢", "suggestions": "🟡", "issues": "🔴"}


@dataclass
class RenderedSlack:
    blocks: list[dict]
    fallback: str


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _one_line(s: str) -> str:
    return " ".join(s.split()).strip()


def _header_verb(v: str) -> str:
    return {"approve": "Approved", "issues": "Changes requested", "suggestions": "Suggestions"}[v]


def _counts_line(comments) -> Optional[str]:
    if not comments:
        return None
    issues = sum(1 for c in comments if c.severity == "issue")
    suggestions = sum(1 for c in comments if c.severity == "suggestion")
    parts = []
    if issues:
        parts.append(f"{issues} {'issue' if issues == 1 else 'issues'}")
    if suggestions:
        parts.append(f"{suggestions} {'suggestion' if suggestions == 1 else 'suggestions'}")
    return " · ".join(parts)


def _summarize_tool_calls(tool_calls: list[ToolCallTrace]) -> str:
    if not tool_calls:
        return ""
    reads = sum(1 for t in tool_calls if t.name == "read_file")
    searches = sum(1 for t in tool_calls if t.name == "search_code")
    refs = sum(1 for t in tool_calls if t.name == "find_references")
    history = sum(1 for t in tool_calls if t.name == "get_file_history")
    rules = sum(1 for t in tool_calls if t.name == "read_review_rules")
    parts = []
    if reads:
        parts.append(f"{reads} read{'' if reads == 1 else 's'}")
    if searches:
        parts.append(f"{searches} search{'' if searches == 1 else 'es'}")
    if refs:
        parts.append(f"{refs} ref lookup{'' if refs == 1 else 's'}")
    if history:
        parts.append(f"{history} history check{'' if history == 1 else 's'}")
    if rules:
        parts.append("review rules")
    return " · ".join(parts)


def render_slack_review(
    output: ReviewOutput,
    gate: GateResult,
    *,
    owner: str,
    name: str,
    number: int,
    url: str,
    review_url: Optional[str] = None,
    tool_calls: Optional[list[ToolCallTrace]] = None,
    prior_verdict: Optional[str] = None,
) -> RenderedSlack:
    tool_calls = tool_calls or []
    blocks: list[dict] = []

    v = gate.final_verdict
    counts = _counts_line(output.line_comments)
    # Card title (header block renders the verdict pill + verb).
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"{VERDICT_PILL[v]} {_header_verb(v)} — PR #{number}", "emoji": True},
    })
    ctx = f"`{owner}/{name}` · <{url}|view PR>"
    if counts:
        ctx += f" · {counts}"
    blocks.append(_context(ctx))
    blocks.append(_section(to_mrkdwn(_escape(output.summary))))

    if prior_verdict and prior_verdict != gate.final_verdict:
        blocks.append(
            _context(
                f"_Verdict changed: *{_header_verb(prior_verdict)}* → "
                f"*{_header_verb(gate.final_verdict)}*_"
            )
        )
        reasoning = (output.reasoning_summary or "").strip()
        if reasoning:
            blocks.append(_context(f"_Why:_ {to_mrkdwn(_escape(_one_line(reasoning)))}"))
        for w in (output.withdrawn_findings or [])[:3]:
            cited = ", ".join(f"`{p}`" for p in w.evidence_paths)
            blocks.append(
                _context(
                    f"_Withdrew `{w.prior_path}:{w.prior_line}`:_ {to_mrkdwn(_escape(_one_line(w.reason)))} "
                    f"_(verified against: {cited})_"
                )
            )

    sorted_findings = sorted(output.line_comments, key=lambda c: SEVERITY_RANK[c.severity])
    top = sorted_findings[:3]
    if top:
        bullets = "\n".join(
            f"{i + 1}. {SEVERITY_EMOJI[lc.severity]} `{lc.path}:{lc.line}` — {to_mrkdwn(_one_line(lc.body))}"
            for i, lc in enumerate(top)
        )
        blocks.append(_section(bullets))
        if len(sorted_findings) > 3:
            blocks.append(_context(f"+{len(sorted_findings) - 3} more on GitHub"))

    evidence = _summarize_tool_calls(tool_calls)
    if evidence:
        blocks.append(_context(f"_What I checked:_ {evidence}"))

    if gate.soft_note:
        blocks.append(_context(f"_Note: {_escape(gate.soft_note)}._"))
    if gate.downgrade_reason:
        label = (
            "Verdict escalated to Issues"
            if gate.outcome == "escalated_to_request_changes"
            else "Approval downgraded to Suggestions"
        )
        blocks.append(_context(f"_{label}: {_escape(gate.downgrade_reason)}._"))

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View on GitHub"},
                    "url": review_url or url,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Re-review"},
                    "action_id": "rereview_pr",
                    "value": json.dumps({"owner": owner, "name": name, "number": number}),
                },
            ],
        }
    )

    fallback_parts = [f"{_header_verb(gate.final_verdict)} on PR #{number}: {output.summary}"]
    if counts:
        fallback_parts.append(counts)
    fallback_parts.append(url)
    return RenderedSlack(blocks=blocks, fallback=" · ".join(fallback_parts))
