"""Implement an approved change on a writable clone, then open a draft PR.

Split into injectable steps so the orchestration is unit-testable offline:
  _clone_and_run_agent → (clone_path, diff_summary, agent_note[, handle])
  _push_and_pr         → pr_url
implement_task wires them, applies the failure ladder, and returns ImplementResult.
"""
from __future__ import annotations

from typing import Callable, Optional

from bott.agents.build_fix.agent.prompt import IMPLEMENT_SYSTEM_PROMPT
from bott.agents.build_fix.agent.tools import build_implement_tools
from bott.agents.build_fix.core.models import ImplementResult
from bott.agents.code_review.github.clone import CloneHandle, _run, writable_clone
from bott.shared import config
from bott.shared.model import build_model
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.build_fix.pipeline")


def _diff_summary(clone_path: str) -> str:
    r = _run(["git", "diff", "--stat"], cwd=clone_path)
    return (r.stdout or "").strip()


def _tests_status(note: str) -> str:
    """Derive the test outcome from the agent's own report (it is prompted to state
    green / failing / not-run). Honest default is 'not_run' when the note is unclear,
    rather than over-claiming green."""
    n = (note or "").lower()
    if "not run" in n or "no test" in n or "couldn't run" in n or "could not run" in n:
        return "not_run"
    if "fail" in n:
        return "failing"
    if "green" in n or "pass" in n:
        return "green"
    return "not_run"


def _clone_and_run_agent(owner: str, name: str, plan_text: str, *, token, model_id):
    """Clone, run the implement agent over the clone, return (clone_path, diff_summary, note, handle).
    The CloneHandle is intentionally NOT cleaned here — implement_task owns the lifecycle."""
    handle = writable_clone(owner, name, token=token)
    from agno.agent import Agent

    budget = config.implement_budget()
    agent = Agent(
        model=build_model("heavy"),
        tools=build_implement_tools(handle.path),
        system_message=IMPLEMENT_SYSTEM_PROMPT,
        tool_call_limit=budget.max_tool_calls,
        telemetry=False,
        markdown=False,
    )
    run = agent.run(f"Implement this approved plan:\n\n{plan_text}")
    note = getattr(run, "content", "") or ""
    return handle.path, _diff_summary(handle.path), note, handle


def _push_and_pr(owner: str, name: str, clone_path: str, plan_text: str, note: str, *, token) -> str:
    from bott.agents.code_review.github.client import GitHubClient

    branch = config._build_branch_name(plan_text)
    _run(["git", "checkout", "-q", "-b", branch], cwd=clone_path)
    _run(["git", "add", "-A"], cwd=clone_path)
    _run(["git", "commit", "-qm", f"bott: {plan_text[:60]}"], cwd=clone_path)
    push = _run(["git", "push", "-q", "origin", branch], cwd=clone_path)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip()}")
    with GitHubClient(token=token) as gh:
        base = gh.default_branch(owner, name)
        body = (f"{note}\n\n---\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        pr = gh.create_pull(owner, name, title=f"bott: {plan_text[:60]}",
                            head=branch, base=base, body=body, draft=True)
    return pr.get("html_url", "")


def implement_task(owner: str, name: str, plan_text: str, *, token: Optional[str] = None,
                   model_id: Optional[str] = None, post: bool = True,
                   on_progress: Optional[Callable[[str], None]] = None) -> ImplementResult:
    if on_progress:
        on_progress("implementing")
    handle: Optional[CloneHandle] = None
    try:
        result = _clone_and_run_agent(owner, name, plan_text, token=token, model_id=model_id)
        # _clone_and_run_agent returns 4-tuple in real impl, 3-tuple when faked in tests:
        clone_path, diff_summary, note = result[0], result[1], result[2]
        handle = result[3] if len(result) > 3 else None

        if not diff_summary:
            return ImplementResult(opened_pr=False, tests="not_run",
                                   note=note or "No changes were necessary.", diff_summary="")
        if not post:
            return ImplementResult(opened_pr=False, tests="not_run", note=note, diff_summary=diff_summary)

        if on_progress:
            on_progress("opening_pr")
        pr_url = _push_and_pr(owner, name, clone_path, plan_text, note, token=token)
        return ImplementResult(opened_pr=True, tests=_tests_status(note), pr_url=pr_url,
                               note=note, diff_summary=diff_summary)
    finally:
        if handle is not None:
            handle.cleanup()
