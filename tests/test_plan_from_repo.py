"""Tests for plan_from_repo and the handle_task 'plan' branch wiring.

All network/clone/LLM calls are monkeypatched — nothing runs against GitHub or a model.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import bott.agents.build_fix.pipeline as pipeline_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeHandle:
    """Minimal CloneHandle stand-in with a spy on cleanup()."""

    def __init__(self, path: str = "/fake/clone"):
        self.path = path
        self.cleanup = MagicMock()


def _make_fake_agent(plan_content: str):
    """Return a fake agno.agent.Agent class whose .run() yields canned content."""
    fake_run = SimpleNamespace(content=plan_content)
    fake_agent_instance = MagicMock()
    fake_agent_instance.run.return_value = fake_run
    FakeAgent = MagicMock(return_value=fake_agent_instance)
    return FakeAgent, fake_agent_instance


# ---------------------------------------------------------------------------
# plan_from_repo — happy path
# ---------------------------------------------------------------------------

def test_plan_from_repo_returns_agent_plan(monkeypatch):
    """plan_from_repo returns the agent's plan text."""
    handle = _FakeHandle()
    monkeypatch.setattr(pipeline_mod, "writable_clone", lambda owner, name, *, token, branch=None: handle)

    FakeAgent, fake_instance = _make_fake_agent("1. Add /health endpoint\n2. Touch app.py")
    # Patch agno.agent.Agent inside the lazy import block
    fake_agno = SimpleNamespace(agent=SimpleNamespace(Agent=FakeAgent))
    monkeypatch.setitem(sys.modules, "agno", fake_agno)
    monkeypatch.setitem(sys.modules, "agno.agent", SimpleNamespace(Agent=FakeAgent))

    result = pipeline_mod.plan_from_repo("myorg", "myrepo", "add a health endpoint", token="tok")

    assert "Add /health endpoint" in result
    assert "Touch app.py" in result


def test_plan_from_repo_always_cleans_up_on_success(monkeypatch):
    """cleanup() is called even when the agent succeeds."""
    handle = _FakeHandle()
    monkeypatch.setattr(pipeline_mod, "writable_clone", lambda owner, name, *, token, branch=None: handle)

    FakeAgent, _ = _make_fake_agent("some plan")
    monkeypatch.setitem(sys.modules, "agno.agent", SimpleNamespace(Agent=FakeAgent))

    pipeline_mod.plan_from_repo("o", "r", "do thing", token=None)

    handle.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# plan_from_repo — failure paths
# ---------------------------------------------------------------------------

def test_plan_from_repo_returns_fallback_on_clone_error(monkeypatch):
    """When writable_clone raises, plan_from_repo returns the fallback (never raises)."""
    monkeypatch.setattr(pipeline_mod, "writable_clone",
                        lambda owner, name, *, token: (_ for _ in ()).throw(RuntimeError("no clone")))

    result = pipeline_mod.plan_from_repo("o", "r", "my request text", token=None)

    assert "my request text" in result
    assert "Plan generation failed" in result


def test_plan_from_repo_cleans_up_on_agent_exception(monkeypatch):
    """cleanup() is called even when the agent itself raises."""
    handle = _FakeHandle()
    monkeypatch.setattr(pipeline_mod, "writable_clone", lambda owner, name, *, token, branch=None: handle)

    FakeAgent = MagicMock(side_effect=RuntimeError("agent blew up"))
    monkeypatch.setitem(sys.modules, "agno.agent", SimpleNamespace(Agent=FakeAgent))

    result = pipeline_mod.plan_from_repo("o", "r", "original request", token=None)

    handle.cleanup.assert_called_once()
    assert "original request" in result


def test_plan_from_repo_fallback_on_empty_agent_output(monkeypatch):
    """When the agent returns empty content, fall back to the request text."""
    handle = _FakeHandle()
    monkeypatch.setattr(pipeline_mod, "writable_clone", lambda owner, name, *, token, branch=None: handle)

    FakeAgent, _ = _make_fake_agent("")  # empty content
    monkeypatch.setitem(sys.modules, "agno.agent", SimpleNamespace(Agent=FakeAgent))

    result = pipeline_mod.plan_from_repo("o", "r", "raw request", token=None)

    assert result == "raw request"


# ---------------------------------------------------------------------------
# handle_task 'plan' branch — wiring tests
# ---------------------------------------------------------------------------

def _make_task(*, owner, repo, text="do something"):
    return {
        "id": "t1",
        "kind": "plan",
        "user_id": "alice@x.com",
        "args": {
            "owner": owner,
            "repo": repo,
            "text": text,
            "channel": "C1",
            "thread_ts": "ts1",
            "trigger_ts": None,
        },
    }


def _inject_plan_modules(monkeypatch, *, plan_from_repo_fn, draft_plan_text_fn):
    """Inject fake pipeline / planning / planner / approvals into lazy-import slots."""
    fake_pipeline = MagicMock()
    fake_pipeline.plan_from_repo = plan_from_repo_fn
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.pipeline", fake_pipeline)

    fake_planning = MagicMock()
    fake_planning.draft_plan_text = draft_plan_text_fn
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.planning", fake_planning)

    fake_planner = MagicMock()
    fake_planner.run_plan_job = MagicMock()
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.planner", fake_planner)

    fake_approvals = MagicMock()
    monkeypatch.setitem(sys.modules, "bott.shared.approvals", fake_approvals)

    return fake_pipeline, fake_planning, fake_planner


def test_handle_task_plan_uses_plan_from_repo_when_owner_and_repo_present(monkeypatch):
    """When owner AND repo are set, handle_task must call plan_from_repo (not draft_plan_text)."""
    import bott.interfaces.slack_app as app_mod

    plan_from_repo_calls = []
    draft_plan_text_calls = []

    def fake_plan_from_repo(owner, repo, text, *, token, model_id, pr_number=None):
        plan_from_repo_calls.append((owner, repo, text))
        return "REPO PLAN"

    def fake_draft_plan_text(args):
        draft_plan_text_calls.append(args)
        return "DRAFT PLAN"

    monkeypatch.setattr(app_mod, "app_token_for", lambda owner, repo: "ghs_token")
    monkeypatch.setattr(app_mod, "_react", lambda *a, **k: None)

    fake_pipeline, fake_planning, fake_planner = _inject_plan_modules(
        monkeypatch,
        plan_from_repo_fn=fake_plan_from_repo,
        draft_plan_text_fn=fake_draft_plan_text,
    )

    app_mod.handle_task(_make_task(owner="myorg", repo="myrepo", text="open a test PR"))

    assert plan_from_repo_calls, "plan_from_repo was not called"
    assert not draft_plan_text_calls, "draft_plan_text should NOT be called when owner+repo present"
    assert plan_from_repo_calls[0] == ("myorg", "myrepo", "open a test PR")


def test_handle_task_plan_uses_draft_plan_text_when_no_owner(monkeypatch):
    """When owner is absent, handle_task must call draft_plan_text (not plan_from_repo)."""
    import bott.interfaces.slack_app as app_mod

    plan_from_repo_calls = []
    draft_plan_text_calls = []

    def fake_plan_from_repo(owner, repo, text, *, token, model_id, pr_number=None):
        plan_from_repo_calls.append((owner, repo, text))
        return "REPO PLAN"

    def fake_draft_plan_text(args):
        draft_plan_text_calls.append(args)
        return "DRAFT PLAN"

    monkeypatch.setattr(app_mod, "app_token_for", lambda owner, repo: None)
    monkeypatch.setattr(app_mod, "_react", lambda *a, **k: None)

    fake_pipeline, fake_planning, fake_planner = _inject_plan_modules(
        monkeypatch,
        plan_from_repo_fn=fake_plan_from_repo,
        draft_plan_text_fn=fake_draft_plan_text,
    )

    app_mod.handle_task(_make_task(owner=None, repo=None, text="build something"))

    assert draft_plan_text_calls, "draft_plan_text was not called"
    assert not plan_from_repo_calls, "plan_from_repo should NOT be called without owner+repo"


def test_handle_task_plan_uses_draft_plan_text_when_repo_missing(monkeypatch):
    """When owner is set but repo is None, fall back to draft_plan_text."""
    import bott.interfaces.slack_app as app_mod

    plan_from_repo_calls = []
    draft_plan_text_calls = []

    def fake_plan_from_repo(owner, repo, text, *, token, model_id, pr_number=None):
        plan_from_repo_calls.append((owner, repo, text))
        return "REPO PLAN"

    def fake_draft_plan_text(args):
        draft_plan_text_calls.append(args)
        return "DRAFT PLAN"

    monkeypatch.setattr(app_mod, "app_token_for", lambda owner, repo: None)
    monkeypatch.setattr(app_mod, "_react", lambda *a, **k: None)

    fake_pipeline, fake_planning, fake_planner = _inject_plan_modules(
        monkeypatch,
        plan_from_repo_fn=fake_plan_from_repo,
        draft_plan_text_fn=fake_draft_plan_text,
    )

    app_mod.handle_task(_make_task(owner="myorg", repo=None))

    assert draft_plan_text_calls
    assert not plan_from_repo_calls


def test_handle_task_plan_sets_plan_text_from_plan_from_repo(monkeypatch):
    """The plan_text placed in args is the value plan_from_repo returned."""
    import bott.interfaces.slack_app as app_mod

    monkeypatch.setattr(app_mod, "app_token_for", lambda owner, repo: "tok")
    monkeypatch.setattr(app_mod, "_react", lambda *a, **k: None)

    captured_args = {}

    def fake_plan_from_repo(owner, repo, text, *, token, model_id, pr_number=None):
        return "THE CONCRETE PLAN"

    def fake_run_plan_job(args, *, post, create_approval):
        captured_args.update(args)

    fake_pipeline = MagicMock()
    fake_pipeline.plan_from_repo = fake_plan_from_repo
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.pipeline", fake_pipeline)

    fake_planning = MagicMock()
    fake_planning.draft_plan_text = MagicMock(return_value="DRAFT")
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.planning", fake_planning)

    fake_planner = MagicMock()
    fake_planner.run_plan_job = fake_run_plan_job
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.planner", fake_planner)

    fake_approvals = MagicMock()
    monkeypatch.setitem(sys.modules, "bott.shared.approvals", fake_approvals)

    app_mod.handle_task(_make_task(owner="myorg", repo="myrepo"))

    assert captured_args.get("plan_text") == "THE CONCRETE PLAN"
