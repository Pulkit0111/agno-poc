# tests/test_build_pipeline.py
import subprocess

from bott.agents.build_fix import pipeline
from bott.agents.build_fix.core.models import ImplementResult


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
