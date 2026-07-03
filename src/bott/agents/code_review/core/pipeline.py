"""End-to-end review orchestration — port of run.ts (the 10-step pipeline).

fetch essentials -> shallow clone -> run agent -> apply gate -> render. Cleans up
the clone in all cases. Persists nothing in phase 1 (returns a result object); the
optional `post` path (phase 3) posts the review to GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from bott.shared.config import DEFAULT_MODEL, Budget, github_token

from ..agent.diff_hunks import is_anchor_in_diff
from ..github.client import GitHubClient, PrMeta
from ..github.clone import shallow_clone
from ..github.fetch_essentials import PrEssentials, fetch_pr_essentials
from ..rendering.github import RenderedReview, render_github_review
from .runner import AgentRunResult, run_review_agent
from .verdict_gate import (
    GateFile,
    GateResult,
    GateRunCtx,
    PriorReview,
    PrSize,
    apply_gate,
)


@dataclass
class ReviewResult:
    meta: PrMeta
    essentials: PrEssentials
    run: AgentRunResult
    gate: Optional[GateResult]
    rendered: Optional[RenderedReview]
    resolvable_comments: list[dict]
    unresolvable_comments: list[dict]
    posted: Optional[dict] = None
    post_error: str = ""  # set when the review finished but GitHub posting failed


def _post_with_fallback(gh, owner: str, name: str, number: int, rendered,
                        comments: list[dict]) -> tuple[Optional[dict], str]:
    """Post the review with a degrade ladder — a finished review must NEVER be lost to a
    posting error. GitHub 422s an APPROVE/REQUEST_CHANGES review on a PR its author posts
    (Bott reviewing its own build PR is exactly that), and can 422 on comment anchors it
    won't accept. Ladder: as-rendered → COMMENT event (intended verdict noted in the body)
    → body-only COMMENT → give up gracefully with (None, reason)."""
    attempts = [
        (rendered.event, rendered.body, comments),
        ("COMMENT",
         f"> Posted as a comment review — GitHub doesn't allow `{rendered.event}` from the "
         f"PR's own author (this PR was opened by Bott). Intended verdict: "
         f"**{rendered.event}**.\n\n{rendered.body}",
         comments),
        ("COMMENT",
         f"> Posted body-only — GitHub rejected the inline comment anchors. Intended "
         f"verdict: **{rendered.event}**.\n\n{rendered.body}",
         None),
    ]
    last_err = ""
    for event, body, cmts in attempts:
        try:
            return gh.post_review(owner, name, number, body=body, event=event,
                                  comments=cmts), ""
        except Exception as e:  # noqa: BLE001 — degrade, never raise a finished review away
            last_err = str(e)
    return None, last_err


def _split_anchors(essentials: PrEssentials, rendered: RenderedReview):
    patches = {f.filename: f.patch for f in essentials.files}
    resolvable, unresolvable = [], []
    for c in rendered.comments:
        if is_anchor_in_diff(patches, c["path"], c["line"]):
            resolvable.append(c)
        else:
            unresolvable.append(c)
    return resolvable, unresolvable


def review_pr(
    owner: str,
    name: str,
    number: int,
    *,
    model_id: str = DEFAULT_MODEL,
    budget: Optional[Budget] = None,
    token: Optional[str] = None,
    prior_review: Optional[PriorReview] = None,
    prior_review_text: Optional[str] = None,
    post: bool = False,
    use_json_mode: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
    on_tool: Optional[Callable[[str, dict], None]] = None,
) -> ReviewResult:
    def _progress(msg: str) -> None:
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    token = token or github_token()
    gh = GitHubClient(token)
    try:
        _progress("fetch")
        essentials = fetch_pr_essentials(gh, owner, name, number)

        _progress("clone")
        with shallow_clone(
            owner, name, essentials.meta.head_sha, pr_number=number, token=token
        ) as clone:
            _progress("review")
            run = run_review_agent(
                essentials,
                clone.path,
                model_id=model_id,
                budget=budget,
                prior_review=prior_review_text,
                use_json_mode=use_json_mode,
                on_tool=on_tool,
            )
        _progress("verdict")

        if run.output is None:
            # No structured verdict produced — nothing to gate/render.
            return ReviewResult(
                meta=essentials.meta,
                essentials=essentials,
                run=run,
                gate=None,
                rendered=None,
                resolvable_comments=[],
                unresolvable_comments=[],
            )

        ctx = GateRunCtx(
            pr_size=PrSize(
                changed_files=essentials.meta.changed_files or len(essentials.files),
                additions=essentials.meta.additions,
                deletions=essentials.meta.deletions,
            ),
            files=[
                GateFile(path=f.filename, status=f.status, additions=f.additions)
                for f in essentials.reviewable_files
            ],
            ci=essentials.ci,
            tool_calls=run.tool_calls,
            termination=run.termination,
            prior_review=prior_review,
        )
        gate = apply_gate(run.output, ctx)
        rendered = render_github_review(
            run.output,
            gate,
            run.tool_calls,
            prior_verdict=prior_review.verdict if prior_review else None,
        )
        resolvable, unresolvable = _split_anchors(essentials, rendered)

        posted, post_error = (None, "")
        if post:
            posted, post_error = _post_with_fallback(gh, owner, name, number,
                                                     rendered, resolvable)

        return ReviewResult(
            meta=essentials.meta,
            essentials=essentials,
            run=run,
            gate=gate,
            rendered=rendered,
            resolvable_comments=resolvable,
            unresolvable_comments=unresolvable,
            posted=posted,
            post_error=post_error,
        )
    finally:
        gh.close()
