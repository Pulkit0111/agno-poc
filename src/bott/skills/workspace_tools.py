"""Hermes-style 'hands' for Bott: file/terminal/code fenced to one workspace dir, plus
clarify (HITL), session_search (isolation-safe), and skill_manage (self-authoring).

All file/shell/python operations are confined to BOTT_WORKSPACE_DIR. The shell runs only
allowlisted commands. This is the safety model for a single-user POC (no cloud sandbox)."""

from __future__ import annotations

import os
from pathlib import Path

from agno.tools.coding import CodingTools
from agno.tools.python import PythonTools
from agno.tools.user_control_flow import UserControlFlowTools

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.workspace")


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
    return tools
