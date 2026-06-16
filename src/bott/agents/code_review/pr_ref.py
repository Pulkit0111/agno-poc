"""Parse a GitHub PR reference out of free text.

Pulls (owner, repo, number) from a PR URL or an 'owner/repo#number' slug. Used by the
Code Review member's tools so the manager can pass a link along verbatim and let the
specialist resolve it. (The conversational intent classification this module once held
now lives in the manager + bott.manager.personality.)
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"github\.com/([^/\s|>]+)/([^/\s|>]+)/pull/(\d+)")
_SLUG_RE = re.compile(r"\b([\w.-]+)/([\w.-]+)#(\d+)\b")


def extract_pr_ref(text: str):
    """Return (owner, repo, number) from a PR URL or 'owner/repo#number', or None."""
    m = _URL_RE.search(text or "")
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = _SLUG_RE.search(text or "")
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    return None
