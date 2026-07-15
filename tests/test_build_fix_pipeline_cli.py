"""CLI-exec build path — codex_cli.run_codex_exec is monkeypatched, no real binary spawned."""
from __future__ import annotations

from bott.agents.build_fix import pipeline as bp
from bott.shared import codex_cli


def test_plan_via_cli_returns_stripped_text(monkeypatch):
    monkeypatch.setattr(bp, "resolve_model_id", lambda role: "gpt-5.5-build")

    def fake_run_codex_exec(prompt, **kw):
        assert kw["sandbox"] == "read-only"
        assert kw["model_id"] == "gpt-5.5-build"
        return codex_cli.CodexExecResult(text="  do the thing  ", data=None, tokens_used=5)

    monkeypatch.setattr(bp, "run_codex_exec", fake_run_codex_exec)
    assert bp._plan_via_cli("/tmp/clone", "add a button") == "do the thing"


def test_implement_via_cli_returns_stripped_note(monkeypatch):
    monkeypatch.setattr(bp, "resolve_model_id", lambda role: "gpt-5.5-build")

    def fake_run_codex_exec(prompt, **kw):
        assert kw["sandbox"] == "workspace-write"
        assert kw["model_id"] == "gpt-5.5-build"
        return codex_cli.CodexExecResult(text="  implemented X, tests green  ", data=None, tokens_used=5)

    monkeypatch.setattr(bp, "run_codex_exec", fake_run_codex_exec)
    assert bp._implement_via_cli("/tmp/clone", "some plan") == "implemented X, tests green"


def test_implement_via_cli_surfaces_error_as_note(monkeypatch):
    monkeypatch.setattr(bp, "resolve_model_id", lambda role: "gpt-5.5-build")

    def fake_run_codex_exec(prompt, **kw):
        raise codex_cli.CodexCliError("sandbox denied")

    monkeypatch.setattr(bp, "run_codex_exec", fake_run_codex_exec)
    note = bp._implement_via_cli("/tmp/clone", "some plan")
    assert "sandbox denied" in note


def test_plan_from_repo_uses_cli_path(monkeypatch):
    class _FakeHandle:
        path = "/tmp/fake-clone"
        def cleanup(self): pass

    monkeypatch.setattr(bp, "writable_clone", lambda *a, **k: _FakeHandle())
    monkeypatch.setattr(bp, "_plan_via_cli", lambda clone_path, request_text: "cli plan")
    result = bp.plan_from_repo("acme", "widgets", "do X")
    assert result == "cli plan"
