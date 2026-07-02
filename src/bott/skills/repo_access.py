"""Read-only repo-awareness tools.

list_repos  — enumerate repos Bott can act on and whether write access is present.
inspect_repo — fetch a compact summary of any repo Bott has GitHub App access to.
"""

from __future__ import annotations

import re
from typing import Callable

from bott.agents.code_review.github.app_auth import app_permissions_for, app_token_for
from bott.agents.code_review.github.client import GitHubClient
from bott.shared import config
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.skills.repo_access")

# Matches github.com/owner/repo  (with optional .git suffix, optional trailing /?#…)
_REPO_URL_RE = re.compile(
    r"github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?(?:[/?#]|$)", re.I
)
# Matches bare owner/repo token
_REPO_TOKEN_RE = re.compile(r"^([\w.\-]+)/([\w.\-]+?)(?:\.git)?$")

_README_MAX = 1500
_TREE_PREVIEW = 40


def _parse_repo(token: str) -> tuple[str, str] | None:
    """Return (owner, name) from 'owner/repo' or a github.com URL, or None."""
    t = (token or "").strip()
    m = _REPO_URL_RE.search(t)
    if m:
        return m.group(1), m.group(2)
    m = _REPO_TOKEN_RE.match(t)
    if m:
        return m.group(1), m.group(2)
    return None


def list_repos() -> str:
    """List the repos Bott is allowed to build/fix, and whether write (GitHub App)
    access is currently active for each.

    Returns a human-readable summary — one repo per line with a write-access badge.
    """
    repos = config.allowed_post_repos()
    if not repos:
        return (
            "No repos are in the allowlist yet. "
            "Set ALLOWED_POST_REPOS=owner/repo,… to add them."
        )
    lines = ["Repos Bott can act on:"]
    for slug in sorted(repos):
        parsed = _parse_repo(slug)
        if parsed is None:
            lines.append(f"  • {slug}  (malformed slug — skipped)")
            continue
        owner, name = parsed
        try:
            perms = app_permissions_for(owner, name)
        except Exception as exc:  # noqa: BLE001
            log.warning("app_permissions_for %s failed: %s", slug, redact(str(exc)))
            perms = None
        # A mintable token only proves the App is installed — write requires contents:write.
        # A read-only installation would 403 on push, so report it honestly.
        if perms is None:
            badge = "no App access"
        elif perms.get("contents") == "write":
            badge = "✓ write"
        else:
            badge = "read-only (no push — App lacks contents:write)"
        lines.append(f"  • {owner}/{name}  [{badge}]")
    return "\n".join(lines)


def inspect_repo(repo: str) -> str:
    """Fetch a compact overview of a GitHub repo: its README (first ~1 500 chars)
    and the top-level/first ~40 file paths from the recursive tree.

    Args:
        repo: 'owner/repo' or a full GitHub URL (https://github.com/owner/repo).
    """
    parsed = _parse_repo(repo)
    if parsed is None:
        return (
            f"Couldn't parse '{repo}' as a repo reference. "
            "Use 'owner/repo' or a github.com URL."
        )
    owner, name = parsed
    tok: str | None
    try:
        tok = app_token_for(owner, name)
    except Exception as exc:  # noqa: BLE001
        log.warning("app_token_for %s/%s failed: %s", owner, name, redact(str(exc)))
        tok = None
    if not tok:
        return f"I don't have GitHub App access to `{owner}/{name}`."

    try:
        client = GitHubClient(token=tok)
        readme = client.get_readme(owner, name)
        tree = client.get_tree(owner, name, max_entries=_TREE_PREVIEW)
    except Exception as exc:  # noqa: BLE001
        log.error("inspect_repo %s/%s failed: %s", owner, name, redact(str(exc)))
        return f"Couldn't read `{owner}/{name}` right now."

    parts: list[str] = [f"## {owner}/{name}"]

    if readme:
        preview = readme[:_README_MAX]
        if len(readme) > _README_MAX:
            preview += "\n…(truncated)"
        parts.append("### README\n" + preview)
    else:
        parts.append("### README\n(none)")

    if tree:
        parts.append("### Files (first %d)" % len(tree))
        parts.append("\n".join(f"  {p}" for p in tree))
    else:
        parts.append("### Files\n(empty or unavailable)")

    return "\n\n".join(parts)


def repo_access_tools() -> list[Callable]:
    """Return the two read-only repo tools (always — gating is inside each tool)."""
    return [list_repos, inspect_repo]
