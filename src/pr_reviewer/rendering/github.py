"""Render a ReviewOutput + GateResult into a GitHub review — port of render-github.ts.

Produces the review `event` (APPROVE/REQUEST_CHANGES/COMMENT), the markdown `body`,
and the inline `comments` anchored at path:line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..core.models import LineComment, ReviewOutput, WithdrawnFinding
from ..core.types import ToolCallTrace
from ..core.verdict_gate import GateResult, downgrade_footer

SEVERITY_RANK = {"issue": 0, "suggestion": 1}


@dataclass
class RenderedReview:
    event: str  # APPROVE | REQUEST_CHANGES | COMMENT
    body: str
    comments: list[dict] = field(default_factory=list)


def _one_line(s: str) -> str:
    return " ".join(s.split()).strip()


def _severity_tag(s: str) -> str:
    return s.upper()


def _category_label(c: str) -> str:
    return c[:1].upper() + c[1:]


def _finding_prefix(lc: LineComment) -> str:
    parts = [_severity_tag(lc.severity), _category_label(lc.category)]
    if lc.action and lc.action != "edit":
        parts.append(lc.action)
    return f"[{' · '.join(parts)}]"


def _sort_by_severity(comments: list[LineComment]) -> list[LineComment]:
    return sorted(comments, key=lambda c: SEVERITY_RANK[c.severity])


def github_event_for_verdict(v: str) -> str:
    if v == "approve":
        return "APPROVE"
    if v == "issues":
        return "REQUEST_CHANGES"
    return "COMMENT"


def _verdict_label(v: str) -> str:
    return {"approve": "Approved", "suggestions": "Suggestions", "issues": "Issues found"}[v]


def _render_counts_line(comments: list[LineComment]) -> Optional[str]:
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


def _render_verdict_changed(
    prior_verdict: Optional[str],
    final_verdict: str,
    reasoning_summary: str,
    withdrawn_findings: list[WithdrawnFinding],
) -> Optional[str]:
    if not prior_verdict or prior_verdict == final_verdict:
        return None
    lines = [
        "### Verdict changed since last review",
        f"**{_verdict_label(prior_verdict)} → {_verdict_label(final_verdict)}**",
    ]
    reasoning = (reasoning_summary or "").strip()
    if reasoning:
        lines += ["", f"_Why:_ {_one_line(reasoning)}"]
    if withdrawn_findings:
        lines += ["", "**Withdrawn findings:**"]
        for i, w in enumerate(withdrawn_findings):
            cited = ", ".join(f"`{p}`" for p in w.evidence_paths)
            lines.append(
                f"{i + 1}. `{w.prior_path}:{w.prior_line}` — {_one_line(w.reason)} "
                f"_Verified against:_ {cited}"
            )
    return "\n".join(lines)


def _render_inline_body(lc: LineComment) -> str:
    header = f"**{_finding_prefix(lc)}** {lc.body}"
    sc = lc.suggested_change
    if not sc:
        return header
    single_line = "\n" not in sc.new_text and "\n" not in sc.old_text
    if single_line:
        return f"{header}\n\n```suggestion\n{sc.new_text}\n```"
    return f"{header}\n\nProposed change:\n\n```\n{sc.new_text}\n```"


def _summarize_tool_calls(tool_calls: list[ToolCallTrace]) -> list[str]:
    if not tool_calls:
        return []
    reads, searches, refs, history = [], [], [], []
    rules_called = False
    for tc in tool_calls:
        args = tc.args or {}
        if tc.name == "read_file" and isinstance(args.get("path"), str):
            reads.append(args["path"])
        elif tc.name == "search_code" and isinstance(args.get("query"), str):
            searches.append(args["query"])
        elif tc.name == "find_references" and isinstance(args.get("symbol"), str):
            refs.append(args["symbol"])
        elif tc.name == "get_file_history" and isinstance(args.get("path"), str):
            history.append(args["path"])
        elif tc.name == "read_review_rules":
            rules_called = True
    lines: list[str] = []
    if reads:
        uniq = list(dict.fromkeys(reads))
        lines.append(
            f"Read {len(uniq)} {'file' if len(uniq) == 1 else 'files'}: "
            + ", ".join(f"`{p}`" for p in uniq)
        )
    if searches:
        uniq = list(dict.fromkeys(searches))
        lines.append("Searched for: " + ", ".join(f"`{q}`" for q in uniq))
    if refs:
        uniq = list(dict.fromkeys(refs))
        lines.append("Looked up references to: " + ", ".join(f"`{s}`" for s in uniq))
    if history:
        uniq = list(dict.fromkeys(history))
        lines.append("Inspected git history for: " + ", ".join(f"`{p}`" for p in uniq))
    if rules_called:
        lines.append("Checked `.bott/review-rules.md`")
    return lines


def render_github_review(
    output: ReviewOutput,
    gate: GateResult,
    tool_calls: Optional[list[ToolCallTrace]] = None,
    prior_verdict: Optional[str] = None,
) -> RenderedReview:
    tool_calls = tool_calls or []
    event = github_event_for_verdict(gate.final_verdict)

    sections: list[str] = [f"**{output.summary}**"]

    vc = _render_verdict_changed(
        prior_verdict, gate.final_verdict, output.reasoning_summary, output.withdrawn_findings or []
    )
    if vc:
        sections.append(vc)

    counts = _render_counts_line(output.line_comments)
    if counts:
        sections.append(counts)

    sorted_comments = _sort_by_severity(output.line_comments)
    if sorted_comments:
        lines = [
            f"{i + 1}. **{_finding_prefix(lc)}** `{lc.path}:{lc.line}` — {_one_line(lc.body)}"
            for i, lc in enumerate(sorted_comments)
        ]
        sections.append("### Findings\n" + "\n".join(lines))

    evidence = _summarize_tool_calls(tool_calls)
    if evidence:
        sections.append("### What I checked\n" + "\n".join(f"- {e}" for e in evidence))

    footer = downgrade_footer(gate)
    if footer:
        sections.append(footer)

    comments = [
        {"path": lc.path, "line": lc.line, "body": _render_inline_body(lc)}
        for lc in sorted_comments
    ]

    return RenderedReview(event=event, body="\n\n".join(sections), comments=comments)
