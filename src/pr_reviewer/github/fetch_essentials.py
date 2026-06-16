"""Pull the PR essentials the agent loop needs — port of fetch-pr-essentials.ts.

meta + files (full/reviewable/skipped-noise) + capped diff (+ diff_truncated) + CI +
comments + linked issues. The agent reads file contents on demand via tools; only the
capped diff is pre-loaded into the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..agent.noise import is_noise_file
from ..config import DIFF_CAP, PER_FILE_PATCH_CAP
from ..core.types import CiStatus, FileChange
from .client import Comment, GitHubClient, PrMeta

_CLOSING_KEYWORDS = [
    "close", "closes", "closed", "fix", "fixes", "fixed",
    "resolve", "resolves", "resolved",
]
_LINKED_RE = re.compile(
    r"\b(?:" + "|".join(_CLOSING_KEYWORDS) + r")\s+(?:([\w.-]+)/([\w.-]+))?#(\d+)",
    re.IGNORECASE,
)


@dataclass
class LinkedIssue:
    number: int
    raw: str
    owner_repo: Optional[tuple[str, str]] = None


@dataclass
class PrEssentials:
    meta: PrMeta
    files: list[FileChange]
    reviewable_files: list[FileChange]
    skipped_noise_files: list[FileChange]
    diff: str
    diff_truncated: bool
    ci: CiStatus
    issue_comments: list[Comment] = field(default_factory=list)
    review_comments: list[Comment] = field(default_factory=list)
    linked_issues: list[LinkedIssue] = field(default_factory=list)


def parse_linked_issues(body: str) -> list[LinkedIssue]:
    if not body:
        return []
    out: list[LinkedIssue] = []
    seen: set[str] = set()
    for m in _LINKED_RE.finditer(body):
        owner, name, num = m.group(1), m.group(2), m.group(3)
        number = int(num)
        key = f"{owner or ''}/{name or ''}#{number}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            LinkedIssue(
                number=number,
                raw=m.group(0),
                owner_repo=(owner, name) if owner and name else None,
            )
        )
    return out


def fetch_pr_essentials(gh: GitHubClient, owner: str, name: str, number: int) -> PrEssentials:
    meta = gh.get_pr(owner, name, number)
    raw_files = gh.list_files(owner, name, number)
    files = [
        FileChange(
            filename=f.get("filename", ""),
            status=f.get("status", "modified"),
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
            patch=f.get("patch"),
        )
        for f in raw_files
    ]
    comments = gh.list_all_comments(owner, name, number)

    try:
        ci = gh.get_ci_status(owner, name, meta.head_sha)
    except Exception:
        ci = CiStatus(overall="none")

    reviewable: list[FileChange] = []
    skipped: list[FileChange] = []
    for f in files:
        if not f.filename:
            continue
        if f.status == "removed" or is_noise_file(f.filename):
            skipped.append(f)
        else:
            reviewable.append(f)

    parts: list[str] = []
    total = 0
    diff_truncated = False
    for f in reviewable:
        patch = f.patch or ""
        block = f"--- {f.filename} ({f.status})\n{patch[:PER_FILE_PATCH_CAP]}"
        if total + len(block) > DIFF_CAP:
            parts.append("--- [diff truncated — additional files omitted]")
            diff_truncated = True
            break
        parts.append(block)
        total += len(block)

    return PrEssentials(
        meta=meta,
        files=files,
        reviewable_files=reviewable,
        skipped_noise_files=skipped,
        diff="\n\n".join(parts),
        diff_truncated=diff_truncated,
        ci=ci,
        issue_comments=comments.issue_comments,
        review_comments=comments.review_comments,
        linked_issues=parse_linked_issues(meta.body or ""),
    )
