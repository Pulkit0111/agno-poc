# tests/test_build_pipeline.py
import subprocess
import time

import pytest

from bott.agents.build_fix import pipeline
from bott.agents.build_fix.core.models import ImplementResult


def test_pr_body_attributes_bott_not_claude_code():
    # Bott (gpt-5.5/Codex) opens the PR itself — the body must NOT claim "Claude Code".
    body = pipeline._pr_body("Implemented the change; tests green.")
    assert "Claude Code" not in body
    assert "Implemented the change; tests green." in body
    assert "Bott" in body


def test_empty_diff_opens_no_pr(monkeypatch, tmp_path):
    # No file changes in the clone → no PR, explanatory note.
    monkeypatch.setattr(pipeline, "_clone_and_run_agent",
                        lambda *a, **k: (str(tmp_path), "", "no changes were necessary"))
    res = pipeline.implement_task("o", "r", "do nothing", token="x", post=True)
    assert isinstance(res, ImplementResult)
    assert res.opened_pr is False and res.pr_url is None
    assert "no" in res.note.lower()


def test_changes_open_draft_pr(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "_clone_and_run_agent",
                        lambda *a, **k: (str(tmp_path), "a.py | 2 +-", "added endpoint; tests green"))
    monkeypatch.setattr(pipeline, "_push_and_pr",
                        lambda *a, **k: "https://github.com/o/r/pull/5")
    res = pipeline.implement_task("o", "r", "add endpoint", token="x", post=True)
    assert res.opened_pr is True and res.pr_url.endswith("/pull/5")
    assert res.updated_existing is False


def test_pr_number_commits_into_existing_pr_no_new_pr(monkeypatch, tmp_path):
    """implement_task with a pr_number checks out that PR's branch, pushes a follow-up commit
    to it, and does NOT open a new PR (the 'commit into the PR' bug)."""
    monkeypatch.setattr(pipeline, "_pr_head_branch", lambda o, n, num, token: "feature-x")
    captured = {}

    def fake_clone(owner, name, plan_text, *, token, model_id, branch=None):
        captured["branch"] = branch
        return (str(tmp_path), "route.ts | 3 +-", "added tests; tests green")

    monkeypatch.setattr(pipeline, "_clone_and_run_agent", fake_clone)
    monkeypatch.setattr(pipeline, "_push_to_existing_pr",
                        lambda *a, **k: "https://github.com/o/r/pull/2")

    def boom_new_pr(*a, **k):
        raise AssertionError("must NOT open a new PR when pr_number is given")

    monkeypatch.setattr(pipeline, "_push_and_pr", boom_new_pr)

    res = pipeline.implement_task("o", "r", "add tests", token="x", post=True, pr_number=2)
    assert res.opened_pr is True and res.updated_existing is True
    assert res.pr_url.endswith("/pull/2")
    assert captured["branch"] == "feature-x"  # cloned/checked out the PR's head branch


def test_diff_summary_detects_new_untracked_file(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "new_file.py").write_text("print('hi')\n")  # untracked
    summary = pipeline._diff_summary(str(tmp_path))
    assert "new_file.py" in summary  # git diff --stat would MISS this; git status --short catches it


def test_diff_summary_empty_when_clean(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert pipeline._diff_summary(str(tmp_path)) == ""


def test_run_agent_bounded_enforces_wall_clock_budget():
    """A hung/hanging implement agent must fail the job cleanly (so the error reaches the
    worker's failure path → Slack thread), never hang forever."""
    class SlowAgent:
        def run(self, prompt):
            time.sleep(1.0)
            return "too late"

    t0 = time.time()
    with pytest.raises(pipeline.ImplementTimeout) as ei:
        pipeline._run_agent_bounded(SlowAgent(), "go", 0.05)
    assert time.time() - t0 < 0.9        # returned at the budget, not at agent completion
    msg = str(ei.value).lower()
    assert "budget" in msg
    # build_failure_message pattern-matches "timeout"/"timed out" as a TRANSIENT GitHub
    # network problem — the budget error must not trip that and tell the wrong story
    # (so no "BUILD_TIMEOUT_S" in the text either: it CONTAINS the substring "timeout")
    assert "timeout" not in msg and "timed out" not in msg


def test_run_agent_bounded_returns_agent_result():
    class FastAgent:
        def run(self, prompt):
            return f"ran:{prompt}"

    assert pipeline._run_agent_bounded(FastAgent(), "x", 5) == "ran:x"


def test_implement_agent_runs_under_configured_budget(monkeypatch, tmp_path):
    """_clone_and_run_agent must hand ImplementBudget.timeout_s (BUILD_TIMEOUT_S) to the
    bounded runner — the budget existed in config but was never enforced."""
    class _Handle:
        path = str(tmp_path)

        def cleanup(self):
            pass

    monkeypatch.setattr(pipeline, "writable_clone", lambda *a, **k: _Handle())
    monkeypatch.setenv("BUILD_TIMEOUT_S", "123")
    seen = {}

    def fake_bounded(agent, prompt, timeout_s):
        seen["timeout_s"] = timeout_s

        class _Run:
            content = "done; tests green"

        return _Run()

    monkeypatch.setattr(pipeline, "_run_agent_bounded", fake_bounded)
    _path, _diff, note, _handle = pipeline._clone_and_run_agent(
        "o", "r", "plan", token=None, model_id=None)
    assert seen["timeout_s"] == 123
    assert note.startswith("done")
