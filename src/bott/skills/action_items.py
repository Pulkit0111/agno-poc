"""Personal action-items tools — add / list / complete / snooze.

Isolation is enforced the same way as scheduling_tools: user_id is ALWAYS resolved from
run_context (never accepted as a parameter), and every store call includes user_id in the
SQL WHERE clause so cross-user access is impossible.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from agno.run import RunContext
from agno.tools import tool

from bott.shared.identity import IsolationError, require_user_id
from bott.shared.persistence import action_items as _store


def _add_action_item_impl(run_context: RunContext, text: str) -> str:
    try:
        uid = require_user_id(getattr(run_context, "user_id", None))
    except IsolationError:
        return "I couldn't tell who you are, so I won't save this action item."
    now = time.time()
    item_id = _store.add_item(uid, text, now, source="user")
    return f"Added action item #{item_id}: {text}"


def _list_my_action_items_impl(run_context: RunContext) -> str:
    try:
        uid = require_user_id(getattr(run_context, "user_id", None))
    except IsolationError:
        return "I couldn't tell who you are."
    items = _store.list_items(uid)
    if not items:
        return "You have no open action items."
    lines = []
    for it in items:
        status_tag = f" [{it['status']}]" if it["status"] != "open" else ""
        lines.append(f"- #{it['id']}{status_tag}: {it['text']}")
    return "\n".join(lines)


def _complete_action_item_impl(run_context: RunContext, item_id: int) -> str:
    try:
        uid = require_user_id(getattr(run_context, "user_id", None))
    except IsolationError:
        return "I couldn't tell who you are."
    now = time.time()
    ok = _store.complete_item(uid, item_id, now)
    if ok:
        return f"Marked action item #{item_id} as done."
    return f"Action item #{item_id} not found (or it's not yours)."


def _snooze_action_item_impl(run_context: RunContext, item_id: int, until: str) -> str:
    try:
        uid = require_user_id(getattr(run_context, "user_id", None))
    except IsolationError:
        return "I couldn't tell who you are."
    try:
        remind_at = datetime.fromisoformat(until).timestamp()
    except (ValueError, TypeError):
        return (
            f"Couldn't parse '{until}' as a date/time. "
            "Please use ISO format, e.g. '2026-07-10T09:00:00'."
        )
    now = time.time()
    ok = _store.snooze_item(uid, item_id, remind_at, now)
    if ok:
        return f"Snoozed action item #{item_id} until {until}."
    return f"Action item #{item_id} not found (or it's not yours)."


def action_items_tools() -> list[Callable]:
    """Return the four personal action-item tools. Each resolves the caller's user_id
    from run_context — never a parameter — so isolation is guaranteed."""

    @tool(name="add_action_item")
    def add_action_item(run_context: RunContext, text: str) -> str:
        """Capture a personal follow-up or action item for yourself."""
        return _add_action_item_impl(run_context, text)

    @tool(name="list_my_action_items")
    def list_my_action_items(run_context: RunContext) -> str:
        """List your open (and snoozed) action items."""
        return _list_my_action_items_impl(run_context)

    @tool(name="complete_action_item")
    def complete_action_item(run_context: RunContext, item_id: int) -> str:
        """Mark one of YOUR action items as done by its id."""
        return _complete_action_item_impl(run_context, item_id)

    @tool(name="snooze_action_item")
    def snooze_action_item(run_context: RunContext, item_id: int, until: str) -> str:
        """Snooze one of YOUR action items until a specific date/time (ISO format)."""
        return _snooze_action_item_impl(run_context, item_id, until)

    return [add_action_item, list_my_action_items, complete_action_item, snooze_action_item]
