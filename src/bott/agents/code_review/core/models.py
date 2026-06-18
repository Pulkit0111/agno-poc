"""Structured output schema for the review agent.

Faithful port of Bott's `src/flows/review/output-schema.ts` to Pydantic. This
`ReviewOutput` model IS the agent's `output_schema` — the agent investigates with
tools, then emits one of these. The verdict gate (verdict_gate.py) then validates
and may adjust the verdict.

Vocabulary (v3.2): severity {issue, suggestion}; verdict {approve, suggestions,
issues}. Field descriptions matter — they steer the model's structured output.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["approve", "suggestions", "issues"]
Severity = Literal["issue", "suggestion"]
Category = Literal["security", "correctness", "tests", "conventions", "operational"]
Action = Literal["edit", "verify", "future", "discuss"]
Confidence = Literal["high", "medium", "low"]


class SuggestedChange(BaseModel):
    """A concrete one-line fix. Renders as a GitHub ```suggestion``` block."""

    old_text: str = Field(description="Verbatim text being replaced (documents intent).")
    new_text: str = Field(description="Replacement text the author would commit.")


class LineComment(BaseModel):
    """A finding the author should address — a problem, risk, or specific
    improvement. NEVER praise or a description of what the code does. If a file
    has nothing actionable, it gets no line_comment."""

    path: str = Field(description="Path relative to repo root, forward-slashes.")
    line: int = Field(ge=1, description="1-indexed line number on the PR head SHA.")
    body: str = Field(
        max_length=2000,
        description="What's wrong/risky/improvable and what to do about it. NOT praise.",
    )
    severity: Severity = Field(
        description=(
            "'issue' = must be fixed before merge (the gate FORCES the verdict to "
            "'issues' when any issue-severity comment is present); 'suggestion' = "
            "meaningful improvement, not a blocker."
        )
    )
    category: Category = Field(
        description="Concern type — matches the HYPOTHESIS CHECKLIST taxonomy."
    )
    action: Action = Field(
        default="edit",
        description=(
            "What the Apply flow should do: 'edit' (mechanical code change), "
            "'verify' (confirm something, no edit), 'future' (out-of-scope), "
            "'discuss' (open question)."
        ),
    )
    suggested_change: Optional[SuggestedChange] = Field(
        default=None,
        description="Optional single-line fix proposal {old_text, new_text}.",
    )


class WithdrawnFinding(BaseModel):
    """Re-review retraction. When this run drops a prior issue-severity finding,
    it must be declared here with evidence the gate cross-checks against tool calls
    (prevents 'developer pushed back -> bot caved' verdict flips)."""

    prior_path: str = Field(description="Path of the prior finding being withdrawn.")
    prior_line: int = Field(ge=1, description="Line of the prior finding being withdrawn.")
    reason: str = Field(
        min_length=10,
        max_length=1000,
        description="Why the prior concern no longer holds (what changed / was re-read).",
    )
    evidence_paths: list[str] = Field(
        min_length=1,
        max_length=10,
        description=(
            "Every file re-read/searched to verify the reversal. The gate rejects "
            "the flip if a cited path never appears in the tool-call history."
        ),
    )


class ReviewOutput(BaseModel):
    """The agent's structured verdict for one PR review."""

    verdict: Verdict = Field(description="Model-emitted verdict; the gate may adjust it.")
    summary: str = Field(
        max_length=600,
        description="2-4 sentences: what the PR does, what was reviewed, and the key "
        "observations incl. the headline finding (for an approve, what was checked and why "
        "it's solid — never just 'looks good').",
    )
    line_comments: list[LineComment] = Field(
        default_factory=list,
        max_length=50,
        description="Findings only — empty array is correct for a clean approve.",
    )
    withdrawn_findings: list[WithdrawnFinding] = Field(
        default_factory=list,
        max_length=20,
        description="Re-review withdrawals; empty/absent on first-run reviews.",
    )
    reasoning_summary: str = Field(
        default="",
        max_length=500,
        description="≤500 chars: why you reached this verdict (trace-only, never shown).",
    )
    confidence: Confidence = Field(description="Your self-rated certainty.")


# --- legacy normalizers (parity with normalizeLegacy* in output-schema.ts) -----
def normalize_legacy_severity(raw: object) -> Severity:
    if raw in ("issue", "suggestion"):
        return raw  # type: ignore[return-value]
    if raw == "blocker":
        return "issue"
    if raw == "nit":
        return "suggestion"
    return "suggestion"


def normalize_legacy_verdict(raw: object) -> Verdict:
    if raw in ("approve", "suggestions", "issues"):
        return raw  # type: ignore[return-value]
    if raw == "comment":
        return "suggestions"
    if raw == "request_changes":
        return "issues"
    return "approve"
