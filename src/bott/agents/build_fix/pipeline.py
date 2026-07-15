"""Implement an approved change on a writable clone, then open a draft PR.

Split into injectable steps so the orchestration is unit-testable offline:
  _clone_and_run_agent → (clone_path, diff_summary, agent_note[, handle])
  _push_and_pr         → pr_url
implement_task wires them, applies the failure ladder, and returns ImplementResult.
"""
from __future__ import annotations

from typing import Callable, Optional

from bott.agents.build_fix.agent.prompt import IMPLEMENT_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT
from bott.agents.build_fix.core.models import ImplementResult
from bott.agents.code_review.github.clone import CloneHandle, _run, writable_clone
from bott.shared import config
from bott.shared.codex_cli import CodexCliError, run_codex_exec
from bott.shared.model import resolve_model_id
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.build_fix.pipeline")


def plan_from_repo(
    owner: str,
    name: str,
    request_text: str,
    *,
    token: Optional[str] = None,
    model_id: Optional[str] = None,
    pr_number: Optional[int] = None,
) -> str:
    """Clone the repo, run a read-only planning agent, and return a concrete plan string.
    When ``pr_number`` is set, plan against that PR's head branch (so a follow-up commit is
    planned on top of the PR's current code, not the default branch).

    The clone is ALWAYS cleaned up in a finally block — nothing is pushed or persisted.
    On any error (clone failure, agent error) a short fallback text is returned so the
    caller never receives an exception.
    """
    handle: Optional[CloneHandle] = None
    try:
        branch = _pr_head_branch(owner, name, pr_number, token) if pr_number else None
        handle = writable_clone(owner, name, token=token, branch=branch)
        plan_text = _plan_via_cli(handle.path, request_text)
        return plan_text or request_text
    except Exception as exc:  # noqa: BLE001 — never raise into the worker
        log.warning("plan_from_repo failed for %s/%s: %s", owner, name, exc)
        return f"[Plan generation failed — proceeding with raw request]\n\n{request_text}"
    finally:
        if handle is not None:
            handle.cleanup()


def _diff_summary(clone_path: str) -> str:
    """Any change the agent made — including NEW (untracked) files, which `git diff --stat`
    misses. `git status --short` lists untracked (??) + modified entries."""
    r = _run(["git", "status", "--short"], cwd=clone_path)
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


def _pr_head_branch(owner: str, name: str, pr_number: int, token) -> str:
    """The head branch of an existing PR — the branch a follow-up commit must land on."""
    from bott.agents.code_review.github.client import GitHubClient
    with GitHubClient(token=token) as gh:
        return gh.get_pr(owner, name, pr_number).head_ref


def _plan_via_cli(clone_path: str, request_text: str) -> str:
    prompt = f"{PLAN_SYSTEM_PROMPT}\n\nRequested change:\n{request_text}\n\nProduce the plan."
    result = run_codex_exec(prompt, cwd=clone_path, sandbox="read-only",
                            model_id=resolve_model_id("build"),
                            timeout_s=config.codex_cli_timeout_s(), binary=config.codex_cli_binary())
    return result.text.strip()


def _implement_via_cli(clone_path: str, plan_text: str) -> str:
    prompt = f"{IMPLEMENT_SYSTEM_PROMPT}\n\nImplement this approved plan:\n\n{plan_text}"
    try:
        result = run_codex_exec(prompt, cwd=clone_path, sandbox="workspace-write",
                                model_id=resolve_model_id("build"),
                                timeout_s=config.codex_cli_timeout_s(), binary=config.codex_cli_binary())
    except CodexCliError as e:
        return f"[codex exec failed: {e}]"
    return result.text.strip()


def _clone_and_run_agent(owner: str, name: str, plan_text: str, *, token, model_id, branch=None):
    """Clone, run the implement agent over the clone, return (clone_path, diff_summary, note, handle).
    ``branch`` checks out an existing PR's head so the change lands on that PR.
    The CloneHandle is intentionally NOT cleaned here — implement_task owns the lifecycle."""
    handle = writable_clone(owner, name, token=token, branch=branch)
    note = _implement_via_cli(handle.path, plan_text)
    return handle.path, _diff_summary(handle.path), note, handle


def _pr_body(note: str) -> str:
    """PR description = the implement agent's own summary + a Bott attribution. Bott opens
    this PR itself (running on the configured model — gpt-5.5/Codex today), so it is NOT
    'Claude Code'; the footer must say so honestly."""
    return f"{note}\n\n---\n🤖 Opened by *Bott* — Axelerant's engineering teammate."


def _push_to_existing_pr(owner: str, name: str, clone_path: str, plan_text: str, branch: str,
                         pr_number: int, *, token) -> str:
    """Commit the change onto the already-checked-out PR branch and push it to that PR —
    no new branch, no new PR. Returns the existing PR's URL."""
    _run(["git", "add", "-A"], cwd=clone_path)
    _run(["git", "commit", "-qm", f"bott: {plan_text[:60]}"], cwd=clone_path)
    push = _run(["git", "push", "-q", "origin", f"HEAD:{branch}"], cwd=clone_path)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {redact(push.stderr.strip())}")
    return f"https://github.com/{owner}/{name}/pull/{pr_number}"


def _push_and_pr(owner: str, name: str, clone_path: str, plan_text: str, note: str, *, token) -> str:
    from bott.agents.code_review.github.client import GitHubClient

    branch = config._build_branch_name(plan_text)
    _run(["git", "checkout", "-q", "-b", branch], cwd=clone_path)
    _run(["git", "add", "-A"], cwd=clone_path)
    _run(["git", "commit", "-qm", f"bott: {plan_text[:60]}"], cwd=clone_path)
    push = _run(["git", "push", "-q", "origin", branch], cwd=clone_path)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {redact(push.stderr.strip())}")
    with GitHubClient(token=token) as gh:
        base = gh.default_branch(owner, name)
        pr = gh.create_pull(owner, name, title=f"bott: {plan_text[:60]}",
                            head=branch, base=base, body=_pr_body(note),
                            draft=config.build_draft_pr())
    return pr.get("html_url", "")


def implement_task(owner: str, name: str, plan_text: str, *, token: Optional[str] = None,
                   model_id: Optional[str] = None, post: bool = True,
                   on_progress: Optional[Callable[[str], None]] = None,
                   pr_number: Optional[int] = None) -> ImplementResult:
    # NOTE: `model_id` is RESERVED — the implement agent runs on the gateway's "heavy" role
    # (build_model("build")), like the review engine, so this arg is not used to pick the model.
    # Kept for signature stability / future per-task override.
    # `pr_number`: when set, commit into that EXISTING PR's branch instead of opening a new PR.
    if on_progress:
        on_progress("implementing")
    handle: Optional[CloneHandle] = None
    try:
        # For an existing PR, check out its head branch so the change lands on that PR.
        branch = _pr_head_branch(owner, name, pr_number, token) if pr_number else None
        result = _clone_and_run_agent(owner, name, plan_text, token=token, model_id=model_id,
                                      branch=branch)
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
        if pr_number:
            pr_url = _push_to_existing_pr(owner, name, clone_path, plan_text, branch, pr_number,
                                          token=token)
            return ImplementResult(opened_pr=True, tests=_tests_status(note), pr_url=pr_url,
                                   note=note, diff_summary=diff_summary, updated_existing=True)
        pr_url = _push_and_pr(owner, name, clone_path, plan_text, note, token=token)
        return ImplementResult(opened_pr=True, tests=_tests_status(note), pr_url=pr_url,
                               note=note, diff_summary=diff_summary)
    finally:
        if handle is not None:
            handle.cleanup()
