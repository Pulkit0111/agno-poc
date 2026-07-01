from __future__ import annotations


def triage_blocks(diagnosis: str, permalink: str, approval_id: int) -> tuple[list, str]:
    link = f"\n<{permalink}|View in Sentry>" if permalink else ""
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Sentry triage — proposed fix*\n{diagnosis}{link}"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve & implement"},
             "style": "primary", "action_id": "approval_approve", "value": str(approval_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "Dismiss"},
             "action_id": "approval_dismiss", "value": str(approval_id)},
        ]},
    ]
    return blocks, "Sentry triage — proposed fix (approve to implement)."
