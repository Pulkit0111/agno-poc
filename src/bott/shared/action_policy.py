"""The action policy — the guard in "LLM composes → guard authorizes → executor acts".

Bott's general primitives (slack_api / github_api / atlassian_api / http_request) let the
agent attempt *anything*; this module is the single deterministic seam that decides what an
attempt is allowed to DO. Determinism lives here — on what's ALLOWED — never on what's
possible:

  - **allow** — reads, and safe writes (a message, a reaction, an issue comment on an
    allow-listed repo). Executed immediately, logged.
  - **gate**  — world-changing / outward / shared-state writes (merge a PR, delete a message,
    archive a channel, comment on a client-visible Jira ticket). Executed only after a human
    Approve in Slack (the same approval gate the build pipeline uses — doc §9).
  - **deny**  — destructive or identity-risk actions (admin ops, repo deletion, raw code
    writes that belong to the build pipeline, private-network fetches). Refused with a reason
    the agent can relay honestly.

Pure functions, no I/O — trivially unit-testable, and auditable in one file.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse

from bott.shared.config import allowed_post_repos

Verdict = Literal["allow", "gate", "deny"]


@dataclass
class Decision:
    verdict: Verdict
    reason: str = ""


# ---------------------------------------------------------------------------
# Slack — by Web API method name
# ---------------------------------------------------------------------------

_SLACK_READ_PREFIXES = (
    "conversations.", "users.", "team.", "emoji.", "usergroups.", "bots.",
    "reactions.get", "pins.list", "auth.test", "chat.scheduledMessages.",
    "reminders.list", "files.info", "files.list", "search.",
)
# Reads that would otherwise match a write-ish prefix are listed explicitly above.
_SLACK_SAFE_WRITES = {
    "chat.postMessage", "chat.scheduleMessage", "chat.update", "chat.meMessage",
    "chat.deleteScheduledMessage",  # undo of its own scheduling — harmless
    "reactions.add", "reactions.remove", "pins.add", "pins.remove",
    "conversations.join",  # joining a public channel is benign and often needed to read it
}
_SLACK_GATED = {
    "chat.delete", "conversations.invite", "conversations.kick", "conversations.create",
    "conversations.archive", "conversations.unarchive", "conversations.rename",
    "conversations.setTopic", "conversations.setPurpose", "files.upload", "files.delete",
    "reminders.add", "reminders.delete",
}
# conversations.* is a read prefix; carve the mutating members out first.
_SLACK_CONV_WRITES = {m for m in (_SLACK_GATED | _SLACK_SAFE_WRITES) if m.startswith("conversations.")}


def _classify_slack(method: str) -> Decision:
    m = (method or "").strip()
    if m.startswith("admin.") or m.startswith("apps."):
        return Decision("deny", "Slack admin/app-management methods are off-limits.")
    if m in _SLACK_SAFE_WRITES:
        return Decision("allow")
    if m in _SLACK_GATED:
        return Decision("gate", "This changes shared Slack state — needs a human approve.")
    if m in _SLACK_CONV_WRITES:  # safety net; already covered above
        return Decision("gate", "This changes shared Slack state — needs a human approve.")
    if any(m.startswith(p) for p in _SLACK_READ_PREFIXES):
        return Decision("allow")
    return Decision("deny", f"Slack method '{m}' isn't in Bott's allowed set.")


# ---------------------------------------------------------------------------
# GitHub — by HTTP verb + REST path
# ---------------------------------------------------------------------------

_GH_REPO_PATH = re.compile(r"^/repos/([\w.-]+)/([\w.-]+)(/|$)")
# Safe conversational writes on an allow-listed repo: issue/PR comments, labels, issues,
# assignees, review comments, reactions.
_GH_SAFE_WRITE = re.compile(
    r"^/repos/[\w.-]+/[\w.-]+/(issues(/\d+)?(/comments|/labels|/assignees)?|"
    r"pulls/\d+/(comments|requested_reviewers)|comments/\d+/reactions|labels)$"
)
_GH_DENY = re.compile(r"/(contents/|git/refs|git/commits|forks$|transfer$|keys|hooks|collaborators)")


def _classify_github(verb: str, path: str) -> Decision:
    v = (verb or "GET").upper()
    p = (path or "").split("?")[0].rstrip("/") or "/"
    if v == "GET":
        return Decision("allow")
    if v == "DELETE":
        return Decision("deny", "Destructive GitHub deletes are off-limits from chat.")
    if _GH_DENY.search(p + "/"):
        return Decision("deny", "Raw code/repo-surgery writes belong to the build pipeline "
                                "(plan → approve → implement), not direct API calls.")
    m = _GH_REPO_PATH.match(p)
    if m:
        allow = allowed_post_repos()
        slug = f"{m.group(1)}/{m.group(2)}".lower()
        if allow and slug not in allow:
            return Decision("deny", f"`{slug}` isn't in the write allowlist (ALLOWED_POST_REPOS).")
    if v in ("POST", "PATCH") and _GH_SAFE_WRITE.match(p):
        return Decision("allow")
    return Decision("gate", "This GitHub write changes shared state — needs a human approve.")


# ---------------------------------------------------------------------------
# Atlassian (Jira + Confluence) — by HTTP verb + REST path
# ---------------------------------------------------------------------------

def _classify_atlassian(verb: str, path: str) -> Decision:
    v = (verb or "GET").upper()
    if v == "GET":
        return Decision("allow")
    if v == "DELETE":
        return Decision("deny", "Deleting Jira/Confluence content is off-limits from chat.")
    # All Jira/Confluence writes are potentially client-visible → human approve.
    return Decision("gate", "Jira/Confluence writes can be client-visible — needs a human approve.")


# ---------------------------------------------------------------------------
# Generic HTTP — GET-only, public hosts only
# ---------------------------------------------------------------------------

def _is_private_host(host: str) -> bool:
    h = (host or "").lower().strip("[]")
    if h in ("localhost",) or h.endswith(".local") or h.endswith(".internal"):
        return True
    try:
        return ipaddress.ip_address(h).is_private or ipaddress.ip_address(h).is_loopback \
            or ipaddress.ip_address(h).is_link_local
    except ValueError:
        return False  # a normal domain name


def _classify_http(verb: str, url: str) -> Decision:
    v = (verb or "GET").upper()
    if v != "GET":
        return Decision("deny", "Generic HTTP is read-only (GET) — writes go through a connector.")
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return Decision("deny", "Only http(s) URLs.")
    if _is_private_host(parsed.hostname or ""):
        return Decision("deny", "Private/internal hosts are off-limits.")
    return Decision("allow")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def classify(system: str, method: str, *, path: str = "", url: str = "",
             params: Optional[dict] = None) -> Decision:
    """Classify one attempted action. `system` ∈ slack|github|atlassian|http.
    For slack, `method` is the Web API method name; for github/atlassian it's the HTTP verb
    (with `path`); for http it's the verb (with `url`)."""
    from bott.shared.policy_overrides import get_override
    override = get_override(system, method)
    if override:
        return Decision(verdict=override["verdict"], reason=f"override: {override['reason']}")
    s = (system or "").lower()
    if s == "slack":
        return _classify_slack(method)
    if s == "github":
        return _classify_github(method, path)
    if s == "atlassian":
        return _classify_atlassian(method, path)
    if s == "http":
        return _classify_http(method, url)
    return Decision("deny", f"Unknown system '{system}'.")
