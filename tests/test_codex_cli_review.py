"""CLI-exec review path — codex_cli.run_codex_exec is monkeypatched, no real binary spawned."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from bott.agents.code_review.core import runner as r
from bott.agents.code_review.core.models import ReviewOutput
from bott.shared import codex_cli, config


@dataclass
class _FakeMeta:
    owner: str = "acme"
    name: str = "widgets"
    title: str = "t"
    author_login: str = "dev"
    head_ref: str = "feat"
    base_ref: str = "main"
    head_sha: str = "abc123"
    additions: int = 5
    deletions: int = 1
    body: str = "desc"
    changed_files: int = 1


@dataclass
class _FakeCi:
    overall: str = "pass"
    failing: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    passing: list = field(default_factory=list)


@dataclass
class _FakeEssentials:
    meta: _FakeMeta = field(default_factory=_FakeMeta)
    reviewable_files: list = field(default_factory=list)
    skipped_noise_files: list = field(default_factory=list)
    ci: _FakeCi = field(default_factory=_FakeCi)
    linked_issues: list = field(default_factory=list)
    issue_comments: list = field(default_factory=list)
    review_comments: list = field(default_factory=list)
    diff_truncated: bool = False
    diff: str = "diff --git a/x b/x"
    files: list = field(default_factory=list)


@pytest.fixture(autouse=True)
def _enable_cli(monkeypatch):
    monkeypatch.setenv("CODEX_CLI_EXEC", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "codex")


def test_run_review_agent_uses_cli_when_enabled(monkeypatch):
    good_output = {"verdict": "approve", "summary": "looks fine", "confidence": "high",
                  "line_comments": [], "withdrawn_findings": [], "reasoning_summary": ""}

    def fake_run_codex_exec(prompt, **kw):
        assert kw["output_schema"] is not None
        assert kw["model_id"] == "gpt-5.5-review-alt"  # resolved + anti-affinity applied
        return codex_cli.CodexExecResult(text="", data=good_output, tokens_used=99)

    monkeypatch.setattr(r, "run_codex_exec", fake_run_codex_exec)
    monkeypatch.setattr(r, "resolve_model_id", lambda role: "gpt-5.5")
    monkeypatch.setattr(r, "_review_anti_affinity", lambda model_id, provider: "gpt-5.5-review-alt")
    result = r.run_review_agent(_FakeEssentials(), "/tmp/clone", model_id="codex:gpt-5.5")
    assert result.output.verdict == "approve"
    assert result.engagement_observable is False
    assert result.tool_calls == []
    assert result.termination == "natural"
    assert result.total_tokens == 99
    assert result.model_id == "gpt-5.5-review-alt"  # AgentRunResult labeled with what actually ran


def test_run_review_agent_cli_bad_output_is_no_submission(monkeypatch):
    monkeypatch.setattr(r, "resolve_model_id", lambda role: "gpt-5.5")
    monkeypatch.setattr(r, "_review_anti_affinity", lambda model_id, provider: model_id)

    def fake_run_codex_exec(prompt, **kw):
        return codex_cli.CodexExecResult(text="", data={"nonsense": True}, tokens_used=1)

    monkeypatch.setattr(r, "run_codex_exec", fake_run_codex_exec)
    result = r.run_review_agent(_FakeEssentials(), "/tmp/clone")
    assert result.output is None
    assert result.termination == "no_submission"


def test_run_review_agent_cli_error_is_model_error(monkeypatch):
    monkeypatch.setattr(r, "resolve_model_id", lambda role: "gpt-5.5")
    monkeypatch.setattr(r, "_review_anti_affinity", lambda model_id, provider: model_id)

    def fake_run_codex_exec(prompt, **kw):
        raise codex_cli.CodexCliError("boom")

    monkeypatch.setattr(r, "run_codex_exec", fake_run_codex_exec)
    result = r.run_review_agent(_FakeEssentials(), "/tmp/clone")
    assert result.output is None
    assert result.termination == "model_error"
    assert "boom" in result.error


def test_run_review_agent_default_path_unaffected(monkeypatch):
    monkeypatch.setenv("CODEX_CLI_EXEC", "0")
    called = []
    monkeypatch.setattr(r, "run_codex_exec", lambda *a, **k: called.append(1))
    # Falls through to the Agno path, which will fail fast without a real model/agent —
    # we only need to assert the CLI branch was never taken.
    try:
        r.run_review_agent(_FakeEssentials(), "/tmp/clone")
    except Exception:
        pass
    assert called == []
