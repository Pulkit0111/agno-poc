"""The uniform verdict gate — verbatim port of Bott's `src/flows/review/verdict-gate.ts`.

APPROVE is earned, not assumed. The gate runs AFTER the agent loop (which produces a
ReviewOutput) and BEFORE the renderers. Pure function — no DB / no GitHub calls. The
runner pipes in `ci`, `tool_calls`, and `termination` collected upstream.

10 preconditions; failing one (other than the two escalation rules) downgrades
APPROVE -> SUGGESTIONS; an issue-severity comment or a failed withdrawal escalates
-> ISSUES. A SUGGESTIONS verdict with zero comments is flipped back to APPROVE with
a soft note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from ..config import gate_thresholds
from .models import ReviewOutput
from .types import CiStatus, ToolCallTrace

Termination = Literal["natural", "budget", "no_submission", "model_error"]
Precondition = Literal[
    "ci_green",
    "diff_vs_lookups",
    "depth_of_engagement",
    "claims_backed_by_tools",
    "natural_termination",
    "confidence_not_low",
    "substantive_change_engaged",
    "blocker_must_be_request_changes",
    "withdrawal_evidence",
    "summary_fix_claims_match_withdrawals",
]
Outcome = Literal[
    "approved", "downgraded_to_comment", "escalated_to_request_changes", "none_applied"
]


@dataclass
class PrSize:
    changed_files: int
    additions: int
    deletions: int


@dataclass
class GateFile:
    path: str
    status: str
    additions: int


@dataclass
class PriorIssueFinding:
    path: str
    line: int


@dataclass
class PriorReview:
    verdict: Literal["approve", "suggestions", "issues"]
    issue_findings: list[PriorIssueFinding] = field(default_factory=list)


@dataclass
class GateRunCtx:
    pr_size: PrSize
    files: list[GateFile]
    ci: CiStatus
    tool_calls: list[ToolCallTrace]
    termination: Termination
    prior_review: Optional[PriorReview] = None


@dataclass
class GateDecision:
    precondition: Precondition
    passed: bool
    detail: str


@dataclass
class GateResult:
    original_verdict: str
    final_verdict: str
    decisions: list[GateDecision]
    outcome: Outcome
    downgrade_reason: Optional[str]
    soft_note: Optional[str]


# --- thresholds / constants ---------------------------------------------------
# Sourced from config (env-overridable) at import; defaults preserve prior behavior.
# Kept as module-level names so the gate logic (and tests) reference them directly.
_THRESHOLDS = gate_thresholds()
LARGE_DIFF_FILES = _THRESHOLDS.large_diff_files
LARGE_DIFF_LINES = _THRESHOLDS.large_diff_lines
MIN_LOOKUPS_FOR_LARGE = _THRESHOLDS.min_lookups_for_large
SUBSTANTIVE_NEW_FILE_LINES = _THRESHOLDS.substantive_new_file_lines

HTML_TWIG_RE = re.compile(r"\.html\.twig$", re.IGNORECASE)
REVIEW_WORTHY_YML_RE = re.compile(
    r"\.(services|routing|permissions|links\.menu|links\.task|links\.action|info|"
    r"install|module|libraries|breakpoints|theme|schema)\.yml$",
    re.IGNORECASE,
)

# Phrase patterns signalling a prose "prior finding fixed/addressed/resolved" claim.
FIX_CLAIM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bprior\s+\w+s?\b[^.]{0,80}\b(fixed|addressed|resolved)\b", re.IGNORECASE),
    re.compile(
        r"\b(previously|earlier)\s+(flagged|raised|reported|identified)\b[^.]{0,80}\b(fix|address|resolv)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\ball\s+(the\s+)?prior\b[^.]{0,80}\b(have|are|were)\s+(been\s+)?(fixed|addressed|resolved)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(fixed|addressed)\s+in\s+commit\b", re.IGNORECASE),
]

LOOKUP_TOOLS = {
    "read_file",
    "search_code",
    "find_references",
    "get_file_history",
    "read_review_rules",
}
# read_file alone is "opened it", not "investigated". These signal real tracing.
INVESTIGATIVE_TOOLS = {
    "search_code",
    "find_references",
    "get_file_history",
    "read_review_rules",
}


def _is_markup_or_config(path: str) -> bool:
    p = path.lower()
    if HTML_TWIG_RE.search(p):
        return True
    if p.endswith(".twig"):
        return True
    if p.endswith(".md") or p.endswith(".mdx"):
        return True
    if p.endswith((".css", ".scss", ".sass", ".less")):
        return True
    if p.endswith((".po", ".pot")):
        return True
    if p.endswith((".svg", ".html", ".htm")):
        return True
    if p.endswith(".json"):
        return True
    if p.endswith((".yml", ".yaml")):
        return not REVIEW_WORTHY_YML_RE.search(p)
    return False


def _collect_visited_paths(tool_calls: list[ToolCallTrace]) -> set[str]:
    """Paths the agent demonstrably looked at — scan LOOKUP_TOOLS args for `path`.
    search_code/find_references don't take a path; matching their result paths is
    intentionally NOT done (conservative, matches Bott)."""
    visited: set[str] = set()
    for tc in tool_calls:
        if tc.name not in LOOKUP_TOOLS:
            continue
        args = tc.args or {}
        path = args.get("path")
        if isinstance(path, str) and len(path) > 0:
            visited.add(path)
    return visited


def apply_gate(output: ReviewOutput, ctx: GateRunCtx) -> GateResult:
    decisions: list[GateDecision] = []

    is_large_diff = (
        ctx.pr_size.changed_files >= LARGE_DIFF_FILES
        or ctx.pr_size.additions + ctx.pr_size.deletions >= LARGE_DIFF_LINES
    )

    # 1. CI must pass (or none configured).
    ci_ok = ctx.ci.overall in ("pass", "none")
    decisions.append(
        GateDecision(
            "ci_green",
            ci_ok,
            f"CI {ctx.ci.overall}"
            if ci_ok
            else f"CI {ctx.ci.overall}"
            + (f" ({', '.join(f.name for f in ctx.ci.failing)})" if ctx.ci.failing else ""),
        )
    )

    # 2. Diff size vs lookups.
    lookup_count = sum(1 for c in ctx.tool_calls if c.name in LOOKUP_TOOLS)
    lookups_ok = (not is_large_diff) or lookup_count >= MIN_LOOKUPS_FOR_LARGE
    decisions.append(
        GateDecision(
            "diff_vs_lookups",
            lookups_ok,
            (
                f"large diff ({ctx.pr_size.changed_files} files, "
                f"+{ctx.pr_size.additions}/-{ctx.pr_size.deletions}); {lookup_count} lookup(s)"
            )
            if is_large_diff
            else "small diff; lookup ratio not enforced",
        )
    )

    # 2b. Depth of engagement.
    investigative_count = sum(1 for c in ctx.tool_calls if c.name in INVESTIGATIVE_TOOLS)
    depth_ok = (not is_large_diff) or investigative_count >= 1
    decisions.append(
        GateDecision(
            "depth_of_engagement",
            depth_ok,
            f"{investigative_count} investigative tool call(s) (search_code / find_references / get_file_history / read_review_rules)"
            if is_large_diff
            else "small diff; depth check not enforced",
        )
    )

    # 3. Every line_comment.path must appear in a tool call's args.
    visited_paths = _collect_visited_paths(ctx.tool_calls)
    unbacked = [lc for lc in output.line_comments if lc.path not in visited_paths]
    claims_ok = len(unbacked) == 0
    decisions.append(
        GateDecision(
            "claims_backed_by_tools",
            claims_ok,
            f"all {len(output.line_comments)} line_comment(s) backed"
            if claims_ok
            else f"{len(unbacked)} unbacked claim(s): {', '.join(l.path for l in unbacked)}",
        )
    )

    # 5. Natural termination.
    natural_termination = ctx.termination == "natural"
    decisions.append(
        GateDecision("natural_termination", natural_termination, f"termination: {ctx.termination}")
    )

    # 6. Confidence not low.
    conf_ok = output.confidence != "low"
    decisions.append(
        GateDecision("confidence_not_low", conf_ok, f"confidence: {output.confidence}")
    )

    # 7. Substantive-change engagement.
    substantive_new_files = [
        f
        for f in ctx.files
        if f.status == "added"
        and f.additions >= SUBSTANTIVE_NEW_FILE_LINES
        and not _is_markup_or_config(f.path)
    ]
    has_substantive_add = len(substantive_new_files) > 0
    engaged_somehow = len(output.line_comments) > 0
    substantive_ok = (not has_substantive_add) or engaged_somehow
    decisions.append(
        GateDecision(
            "substantive_change_engaged",
            substantive_ok,
            (
                "substantive new file(s): "
                + ", ".join(f"{f.path} (+{f.additions})" for f in substantive_new_files)
                + f" — {'engaged' if engaged_somehow else 'no issues raised'}"
            )
            if has_substantive_add
            else "no substantive new files",
        )
    )

    # 8. issue severity -> issues verdict (escalation, not downgrade).
    blocker_comments = [lc for lc in output.line_comments if lc.severity == "issue"]
    has_blocker = len(blocker_comments) > 0
    blocker_ok = (not has_blocker) or output.verdict == "issues"
    decisions.append(
        GateDecision(
            "blocker_must_be_request_changes",
            blocker_ok,
            f"{len(blocker_comments)} issue(s); verdict={output.verdict}"
            if has_blocker
            else "no issues",
        )
    )

    # 9. Withdrawal evidence (re-review from a prior `issues` verdict).
    is_rereview_from_issues = (
        ctx.prior_review is not None and ctx.prior_review.verdict == "issues"
    )
    withdrawal_ok = True
    withdrawal_detail = "no prior issues to withdraw"
    if is_rereview_from_issues and ctx.prior_review is not None:
        prior = ctx.prior_review.issue_findings
        current_by_key = {f"{lc.path}:{lc.line}" for lc in output.line_comments}
        withdrawn_by_key = {
            f"{w.prior_path}:{w.prior_line}": w for w in (output.withdrawn_findings or [])
        }
        violations: list[str] = []
        for finding in prior:
            key = f"{finding.path}:{finding.line}"
            if key in current_by_key:
                continue
            w = withdrawn_by_key.get(key)
            if w is None:
                violations.append(f"{key} (dropped without withdrawn_findings entry)")
                continue
            cited = [p for p in w.evidence_paths if p in visited_paths]
            if len(cited) == 0:
                violations.append(
                    f"{key} (evidence_paths cite no visited file: {', '.join(w.evidence_paths)})"
                )
        withdrawal_ok = len(violations) == 0
        withdrawal_detail = (
            f"{len(prior)} prior issue(s); withdrawals all evidenced"
            if withdrawal_ok
            else "; ".join(violations)
        )
    decisions.append(GateDecision("withdrawal_evidence", withdrawal_ok, withdrawal_detail))

    # 10. Fix-claim discipline.
    summary_text = f"{output.summary} {output.reasoning_summary or ''}"
    fix_claim_match = next((p for p in FIX_CLAIM_PATTERNS if p.search(summary_text)), None)
    has_fix_claim = fix_claim_match is not None
    withdrawals_count = len(output.withdrawn_findings or [])
    fix_claims_ok = (not has_fix_claim) or withdrawals_count > 0
    decisions.append(
        GateDecision(
            "summary_fix_claims_match_withdrawals",
            fix_claims_ok,
            (
                f"summary claims a prior fix; {withdrawals_count} withdrawn_findings entry/entries support it"
                if fix_claims_ok
                else f"summary claims a prior fix (matched: {fix_claim_match.pattern}) but no withdrawn_findings entry — flip is unverified"
            )
            if has_fix_claim
            else "no prior-fix claim in summary",
        )
    )

    final_verdict = output.verdict
    downgrade_reason: Optional[str] = None

    # Downgrade path: approve -> suggestions when any precondition fails (except
    # the two escalation rules, which have their own steps below).
    if output.verdict == "approve":
        failed = [
            d
            for d in decisions
            if not d.passed
            and d.precondition != "blocker_must_be_request_changes"
            and d.precondition != "withdrawal_evidence"
        ]
        if failed:
            final_verdict = "suggestions"
            downgrade_reason = "; ".join(d.detail for d in failed)

    # v3.6 fix-claim downgrade-in-place for SUGGESTIONS.
    if (
        not fix_claims_ok
        and final_verdict == "suggestions"
        and "summary claims a prior fix" not in (downgrade_reason or "")
    ):
        fix_claim_summary = (
            "summary claims a prior fix without a withdrawn_findings entry — claim is unverified"
        )
        downgrade_reason = (
            f"{downgrade_reason}; {fix_claim_summary}" if downgrade_reason else fix_claim_summary
        )

    # Escalation: any issue-severity comment forces issues.
    if has_blocker and final_verdict != "issues":
        final_verdict = "issues"
        blocker_summary = f"{len(blocker_comments)} issue(s) — verdict escalated to issues"
        downgrade_reason = (
            f"{downgrade_reason}; {blocker_summary}" if downgrade_reason else blocker_summary
        )

    # Withdrawal-evidence escalation: refuse an unevidenced verdict flip.
    if not withdrawal_ok and final_verdict != "issues":
        final_verdict = "issues"
        withdrawal_summary = (
            f"withdrawal-evidence gate refused verdict flip — {withdrawal_detail}"
        )
        downgrade_reason = (
            f"{downgrade_reason}; {withdrawal_summary}" if downgrade_reason else withdrawal_summary
        )

    # v3.2: SUGGESTIONS with zero findings -> flip back to APPROVE with soft note.
    soft_note: Optional[str] = None
    if final_verdict == "suggestions" and len(output.line_comments) == 0:
        soft_note = downgrade_reason
        final_verdict = "approve"
        downgrade_reason = None

    if final_verdict == output.verdict:
        outcome: Outcome = "approved" if output.verdict == "approve" else "none_applied"
    elif final_verdict == "issues":
        outcome = "escalated_to_request_changes"
    elif soft_note is not None:
        outcome = "approved"
    else:
        outcome = "downgraded_to_comment"

    return GateResult(
        original_verdict=output.verdict,
        final_verdict=final_verdict,
        decisions=decisions,
        outcome=outcome,
        downgrade_reason=downgrade_reason,
        soft_note=soft_note,
    )


def downgrade_footer(gate: GateResult) -> Optional[str]:
    """Footer line appended to the GitHub review body explaining a verdict change."""
    if gate.downgrade_reason is None:
        return None
    if gate.outcome == "escalated_to_request_changes":
        return f"_Verdict was escalated to ISSUES because: {gate.downgrade_reason}._"
    return f"_Approval was downgraded to SUGGESTIONS because: {gate.downgrade_reason}._"
