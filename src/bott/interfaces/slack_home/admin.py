# src/bott/interfaces/slack_home/admin.py
"""Admin observability panel for the Slack App Home tab.

Read-only: recent jobs, job counts, pending-approval backlog, and active model/Codex
status. Returns an empty list for non-admins (panel is admin-gated).
"""

from __future__ import annotations

_STATUS_ICON = {"done": "✓", "failed": "✗", "pending": "⏳", "running": "⚙"}


def _job_icon(status: str) -> str:
    return _STATUS_ICON.get(status, "?")


def admin_section(is_admin: bool) -> list[dict]:
    """Return compact Slack blocks for the admin observability panel.

    Returns an empty list when *is_admin* is False so the panel is completely absent
    for non-admin users.
    """
    if not is_admin:
        return []

    # Lazy imports — avoid paying the DB round-trip cost for non-admins.
    from bott.interfaces.slack_home.models import _active
    from bott.shared import approvals as _approvals
    from bott.shared import codex_tokens
    from bott.shared.persistence import queue as _queue

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text",
                                     "text": "🛠️ Admin — system", "emoji": True}},
    ]

    # --- Jobs section ---
    jobs = _queue.recent_jobs(limit=8)
    counts = _queue.job_counts()

    if jobs:
        lines = [f"`{j['kind']}` {_job_icon(j['status'])}" for j in jobs]
        jobs_text = "  ·  ".join(lines)
    else:
        jobs_text = "_no jobs yet_"

    # Counts summary: only surface non-zero, non-done entries for signal.
    interesting = {s: n for s, n in counts.items() if s != "done" and n > 0}
    if interesting:
        count_parts = [f"{n} {s}" for s, n in interesting.items()]
        counts_line = ", ".join(count_parts)
    else:
        total_done = counts.get("done", 0)
        counts_line = f"{total_done} done" if total_done else "queue empty"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Jobs*\n{jobs_text}\n_{counts_line}_",
        },
    })

    # --- Approvals section ---
    pcount = _approvals.pending_count()
    plist = _approvals.pending(limit=5)

    if plist:
        apr_lines = [f"`{a['action']}` — {a['summary'][:60]}" for a in plist]
        apr_text = "\n".join(apr_lines)
    else:
        apr_text = "_none_"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Approvals* ({pcount} pending)\n{apr_text}",
        },
    })

    # --- Model / Codex status ---
    a = _active()
    codex = "connected" if codex_tokens.is_connected() else "not connected"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*Model status*\n"
                f"provider: `{a['provider']}`  ·  chat: `{a['chat']}`  ·  "
                f"build: `{a['build']}`  ·  review: `{a['review']}`\nOrg Codex: *{codex}*"
            ),
        },
    })

    return blocks
