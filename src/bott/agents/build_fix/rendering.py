from __future__ import annotations

from bott.agents.build_fix.core.models import ImplementPlan, ImplementResult


def plan_blocks(plan: ImplementPlan, approval_id: int) -> tuple[list, str]:
    lines = [f"*Plan:* {plan.summary}"]
    if plan.steps:
        lines.append("\n".join(f"• {s}" for s in plan.steps))
    if plan.test_plan:
        lines.append(f"*Tests:* {plan.test_plan}")
    if plan.risks:
        lines.append(f"*Risks:* {plan.risks}")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(lines)}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve"},
             "style": "primary", "action_id": "approval_approve", "value": str(approval_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "Dismiss"},
             "action_id": "approval_dismiss", "value": str(approval_id)},
        ]},
    ]
    return blocks, f"Plan: {plan.summary}"


def result_blocks(result: ImplementResult) -> tuple[list, str]:
    if result.opened_pr:
        tail = {"green": "tests green ✓", "failing": "tests still failing ⚠",
                "not_run": "tests not run ⚠"}.get(result.tests, "")
        text = f"Opened a draft PR — {tail}\n{result.pr_url}"
    else:
        text = f"No PR opened. {result.note or ''}"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}], text
