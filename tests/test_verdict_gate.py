"""Port of Bott's verdict-gate.test.ts — parity coverage for the verdict gate.

Pure: no LLM, no network. This is where most of the review-quality parity lives.
"""

from __future__ import annotations

import re

from bott.agents.code_review.core.models import LineComment, ReviewOutput, WithdrawnFinding
from bott.agents.code_review.core.types import CiCheck, CiStatus, ToolCallTrace
from bott.agents.code_review.core.verdict_gate import (
    GateFile,
    GateRunCtx,
    PriorIssueFinding,
    PriorReview,
    PrSize,
    apply_gate,
    downgrade_footer,
)


def tc(name: str, args: dict | None = None) -> ToolCallTrace:
    return ToolCallTrace(name=name, args=args or {})


BASELINE_FINDING = LineComment(
    path="src/foo.ts",
    line=12,
    body="consider documenting this",
    severity="suggestion",
    category="conventions",
)


def baseline_ctx(**over) -> GateRunCtx:
    defaults = dict(
        pr_size=PrSize(changed_files=2, additions=30, deletions=5),
        files=[
            GateFile(path="src/foo.ts", status="modified", additions=20),
            GateFile(path="src/bar.ts", status="modified", additions=10),
        ],
        ci=CiStatus(overall="pass"),
        tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
        termination="natural",
        prior_review=None,
    )
    defaults.update(over)
    return GateRunCtx(**defaults)


def baseline_output(**over) -> ReviewOutput:
    defaults = dict(
        verdict="approve",
        summary="lgtm",
        line_comments=[],
        reasoning_summary="",
        confidence="high",
    )
    defaults.update(over)
    return ReviewOutput(**defaults)


# --- core gate -----------------------------------------------------------------
def test_approves_when_all_preconditions_pass():
    r = apply_gate(baseline_output(), baseline_ctx())
    assert r.outcome == "approved"
    assert r.final_verdict == "approve"
    assert r.downgrade_reason is None
    assert r.soft_note is None


def test_downgrades_when_ci_failing_and_findings_exist():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        baseline_ctx(ci=CiStatus(overall="fail", failing=[CiCheck("Tests")])),
    )
    assert r.outcome == "downgraded_to_comment"
    assert r.final_verdict == "suggestions"
    assert re.search(r"CI fail", r.downgrade_reason or "")
    assert r.soft_note is None


def test_downgrades_large_diff_too_few_lookups():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        baseline_ctx(
            pr_size=PrSize(changed_files=10, additions=500, deletions=200),
            tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
        ),
    )
    assert r.outcome == "downgraded_to_comment"
    assert r.final_verdict == "suggestions"
    assert re.search(r"large diff", r.downgrade_reason or "")


def test_approves_large_diff_with_enough_lookups():
    r = apply_gate(
        baseline_output(line_comments=[]),
        baseline_ctx(
            pr_size=PrSize(changed_files=10, additions=500, deletions=200),
            tool_calls=[
                tc("read_file", {"path": "src/a.ts"}),
                tc("read_file", {"path": "src/b.ts"}),
                tc("search_code", {"query": "foo"}),
            ],
        ),
    )
    assert r.outcome == "approved"


def test_downgrades_large_diff_all_read_file_only():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        baseline_ctx(
            pr_size=PrSize(changed_files=6, additions=120, deletions=0),
            tool_calls=[
                tc("read_file", {"path": "src/foo.ts"}),
                tc("read_file", {"path": "src/b.ts"}),
                tc("read_file", {"path": "src/c.ts"}),
                tc("read_file", {"path": "src/d.ts"}),
                tc("read_file", {"path": "src/e.ts"}),
            ],
        ),
    )
    assert r.outcome == "downgraded_to_comment"
    depth = next(d for d in r.decisions if d.precondition == "depth_of_engagement")
    assert depth.passed is False
    assert re.search(r"investigative tool call", r.downgrade_reason or "")


def test_depth_not_enforced_small_diff():
    r = apply_gate(
        baseline_output(),
        baseline_ctx(
            pr_size=PrSize(changed_files=2, additions=30, deletions=5),
            tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
        ),
    )
    assert r.outcome == "approved"
    depth = next(d for d in r.decisions if d.precondition == "depth_of_engagement")
    assert depth.passed is True
    assert re.search(r"small diff", depth.detail)


def test_substantive_new_file_with_findings_stays_approve():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        GateRunCtx(
            pr_size=PrSize(changed_files=5, additions=120, deletions=3),
            files=[
                GateFile(
                    path="web/modules/custom/esc_core/src/Controller/EndImpersonationSessionController.php",
                    status="added",
                    additions=103,
                ),
                GateFile(
                    path="web/modules/custom/esc_core/esc_core.routing.yml",
                    status="modified",
                    additions=10,
                ),
            ],
            ci=CiStatus(overall="pass"),
            tool_calls=[
                tc("read_file", {"path": "src/foo.ts"}),
                tc("search_code", {"query": "csrf"}),
                tc("read_file", {"path": "src/y.ts"}),
            ],
            termination="natural",
        ),
    )
    assert next(
        d for d in r.decisions if d.precondition == "substantive_change_engaged"
    ).passed is True
    assert r.final_verdict == "approve"


def test_substantive_new_file_engaged():
    r = apply_gate(
        baseline_output(
            line_comments=[
                LineComment(
                    path="src/NewController.ts",
                    line=10,
                    body="consider documenting why CSRF is skipped here",
                    severity="suggestion",
                    category="security",
                )
            ]
        ),
        GateRunCtx(
            pr_size=PrSize(changed_files=5, additions=120, deletions=3),
            files=[
                GateFile(path="src/NewController.ts", status="added", additions=80),
                GateFile(path="routes.ts", status="modified", additions=10),
            ],
            ci=CiStatus(overall="pass"),
            tool_calls=[
                tc("read_file", {"path": "src/NewController.ts"}),
                tc("search_code", {"query": "csrf"}),
                tc("read_file", {"path": "routes.ts"}),
            ],
            termination="natural",
        ),
    )
    assert next(
        d for d in r.decisions if d.precondition == "substantive_change_engaged"
    ).passed is True


def test_substantive_guard_skips_markup_files():
    r = apply_gate(
        baseline_output(line_comments=[]),
        GateRunCtx(
            pr_size=PrSize(changed_files=4, additions=250, deletions=5),
            files=[
                GateFile(
                    path="web/themes/custom/esc/templates/views/views-view--portal-resources--portal-resources.html.twig",
                    status="added",
                    additions=66,
                ),
                GateFile(path="docs/notes.md", status="added", additions=80),
                GateFile(path="web/themes/custom/esc/css/portal.css", status="added", additions=120),
            ],
            ci=CiStatus(overall="pass"),
            tool_calls=[
                tc("read_file", {"path": "web/themes/custom/esc/templates/views/x.html.twig"}),
                tc("search_code", {"query": "portal-resources"}),
                tc("read_file", {"path": "docs/notes.md"}),
            ],
            termination="natural",
        ),
    )
    assert r.outcome == "approved"
    assert next(
        d for d in r.decisions if d.precondition == "substantive_change_engaged"
    ).passed is True


def test_substantive_guard_fires_on_services_yml():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        GateRunCtx(
            pr_size=PrSize(changed_files=2, additions=80, deletions=0),
            files=[
                GateFile(
                    path="web/modules/custom/esc_core/esc_core.services.yml",
                    status="added",
                    additions=80,
                )
            ],
            ci=CiStatus(overall="pass"),
            tool_calls=[
                tc("read_file", {"path": "web/modules/custom/esc_core/esc_core.services.yml"}),
                tc("search_code", {"query": "services"}),
            ],
            termination="natural",
        ),
    )
    assert next(
        d for d in r.decisions if d.precondition == "substantive_change_engaged"
    ).passed is True


def test_substantive_guard_skips_modify_only():
    r = apply_gate(
        baseline_output(line_comments=[]),
        GateRunCtx(
            pr_size=PrSize(changed_files=3, additions=200, deletions=50),
            files=[
                GateFile(path="src/foo.ts", status="modified", additions=100),
                GateFile(path="src/bar.ts", status="modified", additions=100),
            ],
            ci=CiStatus(overall="pass"),
            tool_calls=[
                tc("read_file", {"path": "src/foo.ts"}),
                tc("read_file", {"path": "src/bar.ts"}),
                tc("search_code", {"query": "x"}),
            ],
            termination="natural",
        ),
    )
    assert next(
        d for d in r.decisions if d.precondition == "substantive_change_engaged"
    ).passed is True


def test_downgrades_unbacked_claim():
    r = apply_gate(
        baseline_output(
            line_comments=[
                LineComment(
                    path="src/never-read.ts",
                    line=5,
                    body="x",
                    severity="suggestion",
                    category="correctness",
                )
            ]
        ),
        baseline_ctx(tool_calls=[tc("read_file", {"path": "src/foo.ts"})]),
    )
    assert r.outcome == "downgraded_to_comment"
    assert r.final_verdict == "suggestions"
    assert re.search(r"unbacked claim", r.downgrade_reason or "")


def test_downgrades_on_budget_termination():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        baseline_ctx(termination="budget"),
    )
    assert r.outcome == "downgraded_to_comment"
    assert r.final_verdict == "suggestions"


def test_downgrades_on_low_confidence():
    r = apply_gate(
        baseline_output(confidence="low", line_comments=[BASELINE_FINDING]),
        baseline_ctx(),
    )
    assert r.outcome == "downgraded_to_comment"
    assert r.final_verdict == "suggestions"
    assert re.search(r"confidence: low", r.downgrade_reason or "")


def test_does_not_affect_non_approve():
    r = apply_gate(
        baseline_output(verdict="suggestions", line_comments=[BASELINE_FINDING]),
        baseline_ctx(termination="budget"),
    )
    assert r.outcome == "none_applied"
    assert r.final_verdict == "suggestions"


def test_auto_approve_regression_zero_tool_calls_large_diff():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        baseline_ctx(
            pr_size=PrSize(changed_files=10, additions=500, deletions=0),
            tool_calls=[],
        ),
    )
    assert r.final_verdict == "suggestions"


def test_records_every_precondition():
    r = apply_gate(baseline_output(), baseline_ctx())
    codes = [d.precondition for d in r.decisions]
    for p in (
        "ci_green",
        "diff_vs_lookups",
        "depth_of_engagement",
        "claims_backed_by_tools",
        "natural_termination",
        "confidence_not_low",
        "substantive_change_engaged",
        "blocker_must_be_request_changes",
    ):
        assert p in codes


def test_escalates_suggestions_to_issues_on_issue_severity():
    r = apply_gate(
        baseline_output(
            verdict="suggestions",
            line_comments=[
                LineComment(path="src/foo.ts", line=1, body="leaks token", severity="issue", category="security")
            ],
        ),
        baseline_ctx(),
    )
    assert r.outcome == "escalated_to_request_changes"
    assert r.final_verdict == "issues"
    assert re.search(r"escalated to issues", r.downgrade_reason or "", re.IGNORECASE)


def test_escalates_approve_to_issues():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            line_comments=[
                LineComment(path="src/foo.ts", line=1, body="x", severity="issue", category="correctness")
            ],
        ),
        baseline_ctx(),
    )
    assert r.outcome == "escalated_to_request_changes"
    assert r.final_verdict == "issues"


def test_no_change_when_only_suggestions():
    r = apply_gate(
        baseline_output(
            verdict="suggestions",
            line_comments=[
                LineComment(path="src/foo.ts", line=1, body="minor stylistic", severity="suggestion", category="conventions")
            ],
        ),
        baseline_ctx(),
    )
    assert r.outcome == "none_applied"
    assert r.final_verdict == "suggestions"


def test_explicit_issues_no_double_escalation():
    r = apply_gate(
        baseline_output(
            verdict="issues",
            line_comments=[
                LineComment(path="src/foo.ts", line=1, body="issue body", severity="issue", category="security")
            ],
        ),
        baseline_ctx(),
    )
    assert r.outcome == "none_applied"
    assert r.final_verdict == "issues"


# --- v3.4 withdrawal-evidence gate --------------------------------------------
def test_withdrawal_silent_drop_forced_to_issues():
    r = apply_gate(
        baseline_output(verdict="approve", line_comments=[], confidence="high"),
        baseline_ctx(
            prior_review=PriorReview(
                verdict="issues", issue_findings=[PriorIssueFinding("src/foo.ts", 12)]
            )
        ),
    )
    assert r.final_verdict == "issues"
    assert r.outcome == "escalated_to_request_changes"
    assert re.search(r"withdrawal-evidence", r.downgrade_reason or "")
    assert re.search(r"dropped without withdrawn_findings entry", r.downgrade_reason or "")


def test_withdrawal_allowed_with_cited_evidence():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            line_comments=[],
            confidence="high",
            withdrawn_findings=[
                WithdrawnFinding(
                    prior_path="src/foo.ts",
                    prior_line=12,
                    reason="Re-read src/foo.ts; the autowire alias is registered in services.yml — the prior DI concern doesn't apply.",
                    evidence_paths=["src/foo.ts"],
                )
            ],
        ),
        baseline_ctx(
            tool_calls=[tc("read_file", {"path": "src/foo.ts"}), tc("read_review_rules")],
            prior_review=PriorReview(
                verdict="issues", issue_findings=[PriorIssueFinding("src/foo.ts", 12)]
            ),
        ),
    )
    assert r.final_verdict == "approve"
    assert r.outcome == "approved"


def test_withdrawal_rejects_hallucinated_citation():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            line_comments=[],
            confidence="high",
            withdrawn_findings=[
                WithdrawnFinding(
                    prior_path="src/foo.ts",
                    prior_line=12,
                    reason="I checked the alias config; the prior concern doesn't apply.",
                    evidence_paths=["src/never-visited.yml"],
                )
            ],
        ),
        baseline_ctx(
            tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
            prior_review=PriorReview(
                verdict="issues", issue_findings=[PriorIssueFinding("src/foo.ts", 12)]
            ),
        ),
    )
    assert r.final_verdict == "issues"
    assert r.outcome == "escalated_to_request_changes"
    assert re.search(r"evidence_paths cite no visited file", r.downgrade_reason or "")


def test_withdrawal_not_enforced_when_prior_not_issues():
    r = apply_gate(
        baseline_output(verdict="approve", line_comments=[], confidence="high"),
        baseline_ctx(prior_review=PriorReview(verdict="suggestions", issue_findings=[])),
    )
    assert r.final_verdict == "approve"


def test_withdrawal_allows_reraise_same_finding():
    r = apply_gate(
        baseline_output(
            verdict="issues",
            line_comments=[
                LineComment(
                    path="src/foo.ts",
                    line=12,
                    body="still holds — restated with sharper evidence",
                    severity="issue",
                    category="security",
                )
            ],
            confidence="high",
        ),
        baseline_ctx(
            tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
            prior_review=PriorReview(
                verdict="issues", issue_findings=[PriorIssueFinding("src/foo.ts", 12)]
            ),
        ),
    )
    assert r.final_verdict == "issues"
    assert r.outcome == "none_applied"


def test_withdrawal_multiple_independent():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            line_comments=[],
            confidence="high",
            withdrawn_findings=[
                WithdrawnFinding(
                    prior_path="src/foo.ts",
                    prior_line=12,
                    reason="Re-read; the prior concern is addressed by the new commit.",
                    evidence_paths=["src/foo.ts"],
                )
            ],
        ),
        baseline_ctx(
            tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
            prior_review=PriorReview(
                verdict="issues",
                issue_findings=[PriorIssueFinding("src/foo.ts", 12), PriorIssueFinding("src/bar.ts", 99)],
            ),
        ),
    )
    assert r.final_verdict == "issues"
    assert re.search(r"src/bar\.ts:99", r.downgrade_reason or "")


# --- v3.6 fix-claim discipline -------------------------------------------------
def test_fix_claim_downgrade_without_withdrawals():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            summary="All prior CacheableMetadata findings on 403 responses have been properly fixed in commit abc1234.",
            line_comments=[BASELINE_FINDING],
            confidence="high",
        ),
        baseline_ctx(),
    )
    assert r.final_verdict == "suggestions"
    assert r.outcome == "downgraded_to_comment"
    assert re.search(r"summary claims a prior fix", r.downgrade_reason or "")


def test_fix_claim_allowed_with_withdrawals():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            summary="Prior concerns about season validation have been addressed.",
            line_comments=[],
            confidence="high",
            withdrawn_findings=[
                WithdrawnFinding(
                    prior_path="src/foo.ts",
                    prior_line=12,
                    reason="Re-read src/foo.ts; the season validation now uses is_numeric() per the prior request.",
                    evidence_paths=["src/foo.ts"],
                )
            ],
        ),
        baseline_ctx(
            tool_calls=[tc("read_file", {"path": "src/foo.ts"})],
            prior_review=PriorReview(verdict="issues", issue_findings=[PriorIssueFinding("src/foo.ts", 12)]),
        ),
    )
    assert r.final_verdict == "approve"
    assert r.outcome == "approved"


def test_fix_claim_no_phrasing():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            summary="Adds error boundary to chart components. Clean implementation.",
            line_comments=[],
            confidence="high",
        ),
        baseline_ctx(),
    )
    assert r.final_verdict == "approve"
    d = next(d for d in r.decisions if d.precondition == "summary_fix_claims_match_withdrawals")
    assert d.passed is True
    assert d.detail == "no prior-fix claim in summary"


def test_fix_claim_matches_reasoning_summary():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            summary="Looks good.",
            reasoning_summary="Previously flagged invalid font-weight syntax and missing EOF newline were fixed.",
            line_comments=[BASELINE_FINDING],
            confidence="high",
        ),
        baseline_ctx(),
    )
    assert r.final_verdict == "suggestions"
    assert re.search(r"summary claims a prior fix", r.downgrade_reason or "")


def test_fix_claim_ignores_incidental_fixes_phrasing():
    r = apply_gate(
        baseline_output(
            verdict="approve",
            summary="Fixes a typo in the header and renames the helper.",
            line_comments=[],
            confidence="high",
        ),
        baseline_ctx(),
    )
    assert r.final_verdict == "approve"


def test_fix_claim_recorded_in_decisions():
    r = apply_gate(baseline_output(), baseline_ctx())
    assert "summary_fix_claims_match_withdrawals" in [d.precondition for d in r.decisions]


# --- v3.2 soft-note flip -------------------------------------------------------
def test_softnote_flip_ci_fail_zero_findings():
    r = apply_gate(
        baseline_output(line_comments=[]),
        baseline_ctx(ci=CiStatus(overall="fail", failing=[CiCheck("Tests")])),
    )
    assert r.final_verdict == "approve"
    assert r.outcome == "approved"
    assert r.downgrade_reason is None
    assert re.search(r"CI fail", r.soft_note or "")


def test_softnote_flip_low_confidence_zero_findings():
    r = apply_gate(baseline_output(line_comments=[], confidence="low"), baseline_ctx())
    assert r.final_verdict == "approve"
    assert re.search(r"confidence: low", r.soft_note or "")


def test_softnote_no_flip_with_findings():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING], confidence="low"),
        baseline_ctx(),
    )
    assert r.final_verdict == "suggestions"
    assert r.soft_note is None
    assert re.search(r"confidence: low", r.downgrade_reason or "")


def test_softnote_no_flip_when_escalated_to_issues():
    r = apply_gate(
        baseline_output(
            line_comments=[
                LineComment(path="src/foo.ts", line=1, body="blocker", severity="issue", category="security")
            ],
            confidence="low",
        ),
        baseline_ctx(),
    )
    assert r.final_verdict == "issues"
    assert r.outcome == "escalated_to_request_changes"
    assert r.soft_note is None


# --- downgrade footer ----------------------------------------------------------
def test_footer_null_when_no_downgrade():
    r = apply_gate(baseline_output(), baseline_ctx())
    assert downgrade_footer(r) is None


def test_footer_present_when_downgrade():
    r = apply_gate(
        baseline_output(line_comments=[BASELINE_FINDING]),
        baseline_ctx(termination="budget"),
    )
    assert re.search(r"Approval was downgraded", downgrade_footer(r) or "")


def test_footer_null_on_softnote_flip():
    r = apply_gate(
        baseline_output(line_comments=[]),
        baseline_ctx(termination="budget"),
    )
    assert downgrade_footer(r) is None
