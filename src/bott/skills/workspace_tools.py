"""Hermes-style 'hands' for Bott: file/terminal/code fenced to one workspace dir, plus
clarify (HITL), session_search (isolation-safe), and skill_manage (self-authoring).

All file/shell/python operations are confined to BOTT_WORKSPACE_DIR. The shell runs only
allowlisted commands. This is the safety model for a single-user POC (no cloud sandbox)."""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
from pathlib import Path
from typing import Optional

from agno.run import RunContext
from agno.tools.coding import CodingTools
from agno.tools.python import PythonTools

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.workspace")

# Per-request workspace override: the shared agent (one instance for the whole org) reuses
# the SAME CodingTools/PythonTools objects across every user's turn, so a plain instance
# attribute for "the current base_dir" would race under concurrent requests. A ContextVar
# is scoped per asyncio task / thread, so concurrent users each see only their own value —
# set (and reset) around one tool call by _scope_workspace_to_user below.
_workspace_override: "contextvars.ContextVar[Optional[Path]]" = contextvars.ContextVar(
    "bott_workspace_override", default=None
)


class _ScopedBaseDirMixin:
    """Makes `base_dir` resolve to the current user's subdirectory (via `_workspace_override`)
    when one is set, falling back to the directory the toolkit was constructed with
    otherwise (tests, background jobs, or any call with no resolvable user). The base
    class's `__init__` does a plain `self.base_dir = ...` assignment; because `base_dir` is
    a data descriptor on this subclass, that assignment is captured by the setter below
    instead of shadowing it in the instance `__dict__`."""

    @property
    def base_dir(self) -> Path:
        override = _workspace_override.get()
        return override if override is not None else self._default_base_dir

    @base_dir.setter
    def base_dir(self, value: Path) -> None:
        self._default_base_dir = value


def _user_workspace_dir(user_id: str) -> Path:
    """The sandboxed subdirectory for one user, under the shared workspace root."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id)).strip("_") or "unknown"
    path = Path(config.bott_workspace_dir()) / "_users" / safe
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


@contextlib.contextmanager
def workspace_scope(user_id):
    """Point the workspace tools' base_dir at `user_id`'s own subdirectory for the duration
    of the block (no-op when user_id is falsy). The public seam shared by the Agno tool
    hook below and the MCP server's tool dispatch — both must scope the same way."""
    if not user_id:
        yield
        return
    token = _workspace_override.set(_user_workspace_dir(user_id))
    try:
        yield
    finally:
        _workspace_override.reset(token)


def scope_workspace_to_user(run_context=None, function_call=None, args=None):
    """Agent-wide tool hook: for the duration of one tool call, point the workspace tools'
    `base_dir` at the calling user's own subdirectory instead of the one shared folder.

    Without this, every Slack user's file/code-tool activity landed in the same directory
    on the single shared agent instance — one person's scratch files were readable (and
    overwritable) by anyone else's request. user_id comes from `run_context` (populated by
    the Slack interface from the verified sender), never from the model, so a user can't
    forge someone else's workspace by asking for it in the prompt.

    Falls back to the toolkit's default directory when no user_id is resolvable (tests,
    scripts, or any call made outside a real user turn) — same behavior as before this
    change, so those callers are unaffected.
    """
    args = args or {}
    user_id = getattr(run_context, "user_id", None) if run_context is not None else None
    if not user_id or function_call is None:
        return function_call(**args) if function_call is not None else None
    with workspace_scope(user_id):
        return function_call(**args)


class _HardenedCodingTools(_ScopedBaseDirMixin, CodingTools):
    """CodingTools, with one gap closed on bott's side (not patching the vendored library).

    The base class's dangerous-pattern check (blocking `&&`, `;`, `|`, ...) runs against
    the raw command string, then validates only the FIRST token (via shlex.split) against
    the allowed-commands list. `shlex.split()` treats a literal newline exactly like a
    space, so a command such as "echo hi\\nrm -rf /" passes both checks — its first token
    is the allowlisted `echo` — and is then handed whole to `subprocess.run(..., shell=True)`,
    where a newline is a statement separator to /bin/sh, just like `;`. The second,
    never-checked statement then executes. Reject embedded newlines before the base
    implementation ever sees the command."""

    def _check_command(self, command: str) -> Optional[str]:
        if "\n" in command or "\r" in command:
            return "Error: multi-line shell commands are not allowed in restricted mode."
        return super()._check_command(command)


class _ScopedPythonTools(_ScopedBaseDirMixin, PythonTools):
    """PythonTools, scoped per-user the same way as _HardenedCodingTools (see above)."""


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


def _skill_manage_impl(skills, action: str, name: str, content: str = "") -> str:
    """Create/edit/list SKILL.md files in the library, then reload so they're discoverable."""
    action = (action or "").strip().lower()
    if action == "list":
        return "Skills: " + ", ".join(skills.get_skill_names())
    slug = re.sub(r"[^a-z0-9-]", "-", (name or "").strip().lower()).strip("-")
    if not slug:
        return "A skill needs a kebab-case name."
    if action in ("create", "edit"):
        if "---" not in content or "name:" not in content:
            return "Skill content must start with YAML frontmatter including name + description."
        skill_dir = os.path.join(config.bott_skills_dir(), slug)
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(content)
        try:
            skills.reload()
        except Exception as e:  # noqa: BLE001
            return f"Wrote the skill but reload failed ({e}); it'll load next restart."
        if slug not in skills.get_skill_names():
            return (f"Wrote '{slug}' but it didn't load — check the frontmatter "
                    "(needs valid `name:` and `description:`).")
        return f"Saved skill '{slug}'. It's available now."
    return f"Unknown action '{action}' (use create, edit, or list)."


def ensure_workspace() -> str:
    d = config.bott_workspace_dir()
    os.makedirs(d, exist_ok=True)
    return d


def build_workspace_tools(db=None, skills=None) -> list:
    """The agentic tools (hands + clarify). `db` enables session_search; `skills`
    enables skill_manage — each tool is appended only when its dependency is provided."""
    ws = ensure_workspace()
    tools: list = [
        _HardenedCodingTools(
            base_dir=ws,
            restrict_to_base_dir=True,
            allowed_commands=config.bott_shell_allowed_commands(),
            enable_grep=True,
            enable_find=True,
            enable_ls=True,
        ),
        _ScopedPythonTools(
            base_dir=Path(ws),
            restrict_to_base_dir=True,
            exclude_tools=["read_file", "list_files"],
        ),
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

    if skills is not None:
        from agno.tools import tool

        @tool(name="skill_manage")
        def skill_manage(action: str, name: str = "", content: str = "") -> str:
            """Save or edit a reusable skill (a SKILL.md workflow) so you can reuse it later.
            Use selectively — only when asked, or when a workflow is clearly reusable.

            Args:
                action: "create", "edit", or "list".
                name: kebab-case skill name (for create/edit).
                content: full SKILL.md text with YAML frontmatter (name + description) + body.
            """
            return _skill_manage_impl(skills, action, name, content)

        tools.append(skill_manage)

    return tools
