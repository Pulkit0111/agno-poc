# tests/test_build_pipeline.py
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
