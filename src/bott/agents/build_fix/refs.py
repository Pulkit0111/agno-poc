from __future__ import annotations

import re

from bott.agents.build_fix.core.models import BuildRequest

_ISSUE_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/issues/(\d+)", re.I)
_ISSUE_REF = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
# Bare repo URL: github.com/owner/repo  (no /issues/ path)
_REPO_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/?#]|$)", re.I)
# owner/repo token in prose — greedy on repo name (allows hyphens); must NOT be followed by #N
_REPO_TOKEN = re.compile(r"(?<![/\w])([\w.-]+)/([\w.-]+)(?!#\d)(?:\.git)?(?=[^/#\w.-]|$)")


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
    # 5. owner/repo token anywhere in prose (e.g. "open a PR on Pulkit0111/bott-pr-review-harness")
    m = _REPO_TOKEN.search(t)
    if m:
        owner, repo = m.group(1), m.group(2)
        # Exclude Jira-key-like tokens (all-caps with digits) masquerading as owner/repo
        if not _JIRA_KEY.match(f"{owner}/{repo}"):
            return BuildRequest("request", text=t, owner=owner, repo=repo)
    return BuildRequest("request", text=t)
