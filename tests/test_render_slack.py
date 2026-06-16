import json

from bott.agents.code_review.core.models import LineComment, ReviewOutput
from bott.agents.code_review.core.types import ToolCallTrace
from bott.agents.code_review.core.verdict_gate import GateResult
from bott.agents.code_review.rendering.slack import render_slack_review


def _gate(final="issues", outcome="none_applied", downgrade=None, soft=None, orig=None):
    return GateResult(original_verdict=orig or final, final_verdict=final,
                      decisions=[], outcome=outcome, downgrade_reason=downgrade, soft_note=soft)


def _render(output, gate, **kw):
    return render_slack_review(output, gate, owner="o", name="r", number=42,
                               url="https://github.com/o/r/pull/42", **kw)


def test_issues_render_is_json_serializable_and_has_finding():
    out = ReviewOutput(verdict="issues", summary="leaks a token",
                       line_comments=[LineComment(path="a.py", line=5, body="logs token",
                                                  severity="issue", category="security")],
                       confidence="high")
    r = _render(out, _gate("issues"),
                tool_calls=[ToolCallTrace("read_file", {"path": "a.py"}),
                            ToolCallTrace("search_code", {"query": "token"})])
    json.dumps(r.blocks)  # must serialize
    text = " ".join(b.get("text", {}).get("text", "") for b in r.blocks if b.get("type") == "section")
    assert "Issues found" in text and "a.py:5" in text
    assert "Issues found on PR #42" in r.fallback


def test_approve_render_has_buttons():
    out = ReviewOutput(verdict="approve", summary="looks good", line_comments=[], confidence="high")
    r = _render(out, _gate("approve", outcome="approved"))
    assert any(b["type"] == "actions" for b in r.blocks)


def test_soft_note_rendered():
    out = ReviewOutput(verdict="approve", summary="ok", line_comments=[], confidence="low")
    r = _render(out, _gate("approve", outcome="approved", soft="confidence: low"))
    text = " ".join(e.get("text", "") for b in r.blocks if b.get("type") == "context"
                     for e in b.get("elements", []))
    assert "confidence: low" in text


def test_verdict_changed_block_on_rereview():
    out = ReviewOutput(verdict="approve", summary="addressed now",
                       reasoning_summary="prior issue verified fixed", line_comments=[],
                       confidence="high")
    r = _render(out, _gate("approve", outcome="approved"), prior_verdict="issues")
    text = " ".join(e.get("text", "") for b in r.blocks if b.get("type") == "context"
                     for e in b.get("elements", []))
    assert "Verdict changed" in text
