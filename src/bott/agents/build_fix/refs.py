from __future__ import annotations

import re

from bott.agents.build_fix.core.models import BuildRequest

_ISSUE_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/issues/(\d+)", re.I)
_ISSUE_REF = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def parse_build_target(target: str) -> BuildRequest:
    t = (target or "").strip()
    m = _ISSUE_URL.search(t)
    if m:
        return BuildRequest("github_issue", text=t, owner=m.group(1), repo=m.group(2), issue=int(m.group(3)))
    m = _ISSUE_REF.match(t)
    if m:
        return BuildRequest("github_issue", text=t, owner=m.group(1), repo=m.group(2), issue=int(m.group(3)))
    if _JIRA_KEY.match(t):
        return BuildRequest("jira", text=t, jira_key=t)
    return BuildRequest("request", text=t)
