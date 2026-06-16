"""Re-review continuity — port of the prior-review + answer-context handling.

When a human replies in a review thread, we capture the reply as answer-context,
render the prior review into the PRIOR REVIEW prompt section, and re-run the engine
with the prior verdict + issue findings supplied to the gate. The gate's v3.4/v3.6
rules then make any verdict flip evidence-bound.
"""

from __future__ import annotations

from .models import ReviewOutput
from .verdict_gate import PriorIssueFinding, PriorReview


def prior_issue_findings(prior_output: ReviewOutput) -> list[PriorIssueFinding]:
    return [
        PriorIssueFinding(path=lc.path, line=lc.line)
        for lc in prior_output.line_comments
        if lc.severity == "issue"
    ]


def build_prior_review(prior_output: ReviewOutput, prior_final_verdict: str) -> PriorReview:
    return PriorReview(
        verdict=prior_final_verdict,  # type: ignore[arg-type]
        issue_findings=prior_issue_findings(prior_output),
    )


def build_prior_review_text(
    prior_output: ReviewOutput, prior_final_verdict: str, reply_text: str
) -> str:
    """Rendered block injected into the system prompt's PRIOR REVIEW section."""
    lines = [
        f"PRIOR VERDICT: {prior_final_verdict}",
        f"PRIOR SUMMARY: {prior_output.summary}",
    ]
    if prior_output.line_comments:
        lines.append("PRIOR FINDINGS:")
        for lc in prior_output.line_comments:
            lines.append(f"  - [{lc.severity}] {lc.path}:{lc.line} — {lc.body}")
    else:
        lines.append("PRIOR FINDINGS: (none)")
    reply = (reply_text or "").strip()
    if reply:
        lines += [
            "",
            "REVIEWER FEEDBACK FROM THE THREAD (treat as the human's push-back / new info):",
            f"  {reply}",
        ]
    return "\n".join(lines)
