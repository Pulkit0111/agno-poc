"""Hermes-style 'hands' for Bott: file/terminal/code fenced to one workspace dir, plus
clarify (HITL), session_search (isolation-safe), and skill_manage (self-authoring).

All file/shell/python operations are confined to BOTT_WORKSPACE_DIR. The shell runs only
allowlisted commands. This is the safety model for a single-user POC (no cloud sandbox)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agno.run import RunContext
from agno.tools.coding import CodingTools
from agno.tools.python import PythonTools
from agno.tools.user_control_flow import UserControlFlowTools

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.workspace")


def _session_search_impl(db, run_context: RunContext, query: str, limit: int = 5) -> str:
    """Search THIS user's past sessions for a query string; return matching snippets.
    user_id comes from run_context (never the model) so users can't read each other."""
    user_id = getattr(run_context, "user_id", None)
    if not user_id:
        return "No user context available — can't search your history."
    try:
        sessions = db.get_sessions(user_id=user_id, limit=50) or []
    except Exception as e:  # noqa: BLE001
        log.warning("session_search failed: %s", e)
        return f"Couldn't search your history right now ({e})."
    q = query.lower().strip()
    hits: list[str] = []
    for s in sessions:
        blob = json.dumps(s.to_dict() if hasattr(s, "to_dict") else s, default=str)
        if q and q in blob.lower():
            sid = getattr(s, "session_id", None) or (s.get("session_id") if isinstance(s, dict) else "?")
            idx = blob.lower().find(q)
            snippet = blob[max(0, idx - 120): idx + 160]
            hits.append(f"- session `{sid}`: …{snippet}…")
        if len(hits) >= limit:
            break
    if not hits:
        return f"Nothing in your past sessions matched '{query}'."
    return "Found in your past sessions:\n" + "\n".join(hits)


def ensure_workspace() -> str:
    d = config.bott_workspace_dir()
    os.makedirs(d, exist_ok=True)
    return d


def build_workspace_tools(db=None, skills=None) -> list:
    """The new agentic tools. `db` and `skills` are wired in Tasks 4 and 5."""
    ws = ensure_workspace()
    tools: list = [
        CodingTools(
            base_dir=ws,
            restrict_to_base_dir=True,
            allowed_commands=config.bott_shell_allowed_commands(),
            enable_grep=True,
            enable_find=True,
            enable_ls=True,
        ),
        PythonTools(base_dir=Path(ws), restrict_to_base_dir=True),
        UserControlFlowTools(),
    ]
    if db is not None:
        from agno.tools import tool

        @tool(name="session_search")
        def session_search(run_context: RunContext, query: str, limit: int = 5) -> str:
            """Search your OWN past conversations/decisions with Bott.

            Args:
                query: Words to look for (e.g. a topic or decision).
                limit: Max results (default 5).
            """
            return _session_search_impl(db, run_context, query, limit)

        tools.append(session_search)

    return tools
