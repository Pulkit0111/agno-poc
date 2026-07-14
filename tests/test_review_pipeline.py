"""End-to-end `review_pr` orchestration — fetch/clone/run/gate/render wiring.

Keeps GitHub and the model out of the loop entirely: `fetch_pr_essentials`,
`shallow_clone`, and `run_review_agent` are monkeypatched at the `pipeline` module so
the test only exercises the orchestration glue (gate context construction, rendering,
anchor splitting).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

import bott.agents.code_review.core.pipeline as p
from bott.agents.code_review.core.models import ReviewOutput
from bott.agents.code_review.core.runner import AgentRunResult
from bott.agents.code_review.core.types import CiStatus, FileChange, ToolCallTrace
from bott.agents.code_review.github.client import PrMeta
from bott.agents.code_review.github.fetch_essentials import PrEssentials


def _essentials() -> PrEssentials:
    meta = PrMeta(
        owner="acme", name="widgets", number=7, url="https://github.com/acme/widgets/pull/7",
        title="t", body="desc", author_login="dev", state="open", draft=False,
        head_sha="abc123", base_sha="def456", head_ref="feat", base_ref="main",
        additions=5, deletions=1, changed_files=1,
    )
    files = [FileChange(filename="a.py", status="modified", additions=5, deletions=1, patch="@@ -1 +1 @@")]
    return PrEssentials(
        meta=meta,
        files=files,
        reviewable_files=files,
        skipped_noise_files=[],
        diff="diff --git a/a.py b/a.py",
        diff_truncated=False,
        ci=CiStatus(overall="pass"),
    )


@dataclass
class _FakeCloneHandle:
    path: str = "/tmp/fake-clone-does-not-exist"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _good_output() -> ReviewOutput:
    return ReviewOutput(
        verdict="approve", summary="looks fine", confidence="high",
        line_comments=[], withdrawn_findings=[], reasoning_summary="",
    )


def _patch_common(monkeypatch, run: AgentRunResult):
    monkeypatch.setattr(p, "fetch_pr_essentials", lambda gh, owner, name, number: _essentials())

    @contextmanager
    def _fake_shallow_clone(owner, name, head_sha, *, pr_number=None, token=None):
        yield _FakeCloneHandle()

    monkeypatch.setattr(p, "shallow_clone", _fake_shallow_clone)
    monkeypatch.setattr(p, "run_review_agent", lambda *a, **k: run)


def test_pipeline_default_engagement_observable_is_true(monkeypatch):
    """The Agno path's AgentRunResult defaults engagement_observable=True — the gate must
    see that same default when nothing overrides it."""
    captured = {}
    real_apply_gate = p.apply_gate

    def spy_apply_gate(output, ctx):
        captured["ctx"] = ctx
        return real_apply_gate(output, ctx)

    monkeypatch.setattr(p, "apply_gate", spy_apply_gate)
    run = AgentRunResult(output=_good_output(), tool_calls=[], termination="natural")
    _patch_common(monkeypatch, run)

    result = p.review_pr("acme", "widgets", 7, token="tok")
    assert result.gate is not None
    assert captured["ctx"].engagement_observable is True


def test_pipeline_forwards_engagement_observable(monkeypatch):
    """A CLI-exec run (engagement_observable=False) must reach the gate as such — otherwise
    the gate's default of True would wrongly re-enable the tool-call-cross-check
    preconditions for a run that has no tool_calls trace to check."""
    captured = {}
    real_apply_gate = p.apply_gate

    def spy_apply_gate(output, ctx):
        captured["ctx"] = ctx
        return real_apply_gate(output, ctx)

    monkeypatch.setattr(p, "apply_gate", spy_apply_gate)
    run = AgentRunResult(
        output=_good_output(), tool_calls=[], termination="natural",
        engagement_observable=False,
    )
    _patch_common(monkeypatch, run)

    result = p.review_pr("acme", "widgets", 7, token="tok")
    assert result.gate is not None
    assert captured["ctx"].engagement_observable is False
