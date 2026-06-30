from __future__ import annotations


def draft_plan_text(args: dict) -> str:
    """v1: produce the plan_text the approval shows + the implement agent works from.
    For a plain request, that's the user's text. For a GitHub issue / Jira ticket, reference
    the source — the implement agent has GitHub-read tools and reads the issue/ticket itself
    during implementation. (Richer fetch-and-summarize is a fast follow.)"""
    kind = args.get("kind")
    text = (args.get("text") or "").strip()
    if kind == "github_issue":
        owner, repo, issue = args.get("owner"), args.get("repo"), args.get("issue")
        return f"Implement GitHub issue {owner}/{repo}#{issue}" + (f": {text}" if text else "")
    if kind == "jira":
        return f"Implement Jira ticket {args.get('jira_key')}" + (f": {text}" if text else "")
    return text or "Implement the requested change."
