from __future__ import annotations

from agno.tools.coding import CodingTools

# Commands the implement agent may run inside the clone (superset of the chat workspace
# allowlist; adds the runners needed to build/test a repo).
_IMPLEMENT_SHELL = [
    "git", "python", "python3", "pip", "pytest", "node", "npm", "npx", "yarn",
    "make", "ls", "cat", "echo", "pwd", "head", "tail", "grep", "find", "wc", "sed", "awk",
]


def build_implement_tools(clone_path: str) -> list:
    """Hands for the implement agent: read/edit/write/run-shell fenced to the clone dir."""
    return [
        CodingTools(
            base_dir=clone_path,
            restrict_to_base_dir=True,
            allowed_commands=_IMPLEMENT_SHELL,
            enable_grep=True,
            enable_find=True,
            enable_ls=True,
        ),
    ]
