from __future__ import annotations

import re

from bott.agents.build_fix.core.models import BuildRequest
from bott.shared.config import allowed_post_repos

_ISSUE_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/issues/(\d+)", re.I)
_ISSUE_REF = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
# Bare repo URL: github.com/owner/repo  (no /issues/ path)
_REPO_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/?#]|$)", re.I)
# owner/repo token in prose — greedy on repo name (allows hyphens); must NOT be followed by #N
_REPO_TOKEN = re.compile(r"(?<![/\w])([\w.-]+)/([\w.-]+)(?!#\d)(?:\.git)?(?=[^/#\w.-]|$)")


_BARE_REPO = re.compile(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$")


def parse_repo_ref(s: str) -> tuple[str | None, str | None]:
    """Parse an EXPLICIT repo reference — a bare 'owner/repo' or a github.com URL. No allowlist
    gating (the caller passed this deliberately, so it's not a scraped prose phrase)."""
    s = (s or "").strip()
    m = _REPO_URL.search(s)
    if m:
        return m.group(1), m.group(2)
    m = _BARE_REPO.match(s)
    if m:
        return m.group(1), m.group(2)
    return None, None


def parse_build_target(target: str) -> BuildRequest:
    t = (target or "").strip()
    # 1. GitHub issue URL (highest priority — contains /issues/)
    m = _ISSUE_URL.search(t)
    if m:
        return BuildRequest("github_issue", text=t, owner=m.group(1), repo=m.group(2), issue=int(m.group(3)))
    # 2. owner/repo#N shorthand
    m = _ISSUE_REF.match(t)
    if m:
        return BuildRequest("github_issue", text=t, owner=m.group(1), repo=m.group(2), issue=int(m.group(3)))
    # 3. Jira key
    if _JIRA_KEY.match(t):
        return BuildRequest("jira", text=t, jira_key=t)
    # 4. Bare GitHub repo URL (github.com/owner/repo, no /issues/)
    m = _REPO_URL.search(t)
    if m:
        return BuildRequest("request", text=t, owner=m.group(1), repo=m.group(2))
    # 5. owner/repo token(s) in prose. This is the WEAKEST signal — arbitrary "word/word"
    #    phrases ("docs/auth", "and/or", "read/write") look exactly like a repo. When a build
    #    allowlist is configured, trust ONLY a token that matches it, so a stray phrase is never
    #    cloned as a repo (the docs/auth bug). With no allowlist (dev), fall back to the first
    #    non-Jira token to preserve the old convenience.
    candidates = [(mm.group(1), mm.group(2)) for mm in _REPO_TOKEN.finditer(t)
                  if not _JIRA_KEY.match(f"{mm.group(1)}/{mm.group(2)}")]
    allow = {r.lower() for r in allowed_post_repos()}
    for owner, repo in candidates:
        if f"{owner}/{repo}".lower() in allow:
            return BuildRequest("request", text=t, owner=owner, repo=repo)
    if allow:
        # Allowlist set but nothing matched — don't guess a repo from a prose phrase.
        return BuildRequest("request", text=t)
    if candidates:
        owner, repo = candidates[0]
        return BuildRequest("request", text=t, owner=owner, repo=repo)
    return BuildRequest("request", text=t)
