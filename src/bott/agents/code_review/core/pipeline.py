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

        posted = None
        if post:
            posted = gh.post_review(
                owner,
                name,
                number,
                body=rendered.body,
                event=rendered.event,
                comments=resolvable,
            )

        return ReviewResult(
            meta=essentials.meta,
            essentials=essentials,
            run=run,
            gate=gate,
            rendered=rendered,
            resolvable_comments=resolvable,
            unresolvable_comments=unresolvable,
            posted=posted,
        )
    finally:
        gh.close()
