"""Deterministic user-memory capture through `codex exec` structured output.

Agno's MemoryManager drives memory updates by letting the model CALL TOOLS
(add/update/delete_memory) — but bott's only LLM path is `codex exec`, which runs its own
loop and can't call Agno tools. So this subclass swaps the tool-calling pass for one
codex exec call with an --output-schema of memory OPERATIONS, then applies those ops
through the SAME db-tool closures the base class would have handed the model
(_get_db_tools) — storage, recall (add_memories_to_context) and isolation (user_id-keyed
rows) all stay stock Agno.

Memory capture must never break the chat turn: any codex failure logs and returns a
skip note.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from agno.memory import MemoryManager

from bott.shared import config
from bott.shared.codex_cli import CodexCliError, run_codex_exec
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.codex_memory")

# codex exec runs strict structured outputs; codex_cli._strictify_schema fills in
# additionalProperties/required. Optional fields are nullable rather than omitted.
_OPS_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["add", "update", "delete"]},
                    "memory_id": {"type": ["string", "null"]},
                    "memory": {"type": ["string", "null"]},
                    "topics": {"type": ["array", "null"], "items": {"type": "string"}},
                },
            },
        }
    },
}


def _extraction_prompt(capture_instructions: str, existing_memories: list, user_input: str) -> str:
    existing_lines = "\n".join(
        f"- id={m.get('memory_id')}: {m.get('memory')}" for m in existing_memories or []
    ) or "(none)"
    return (
        "You are a memory manager. Decide which durable facts about this user to add, "
        "update, or delete based on their message. Return ONLY the operations object "
        "matching the schema; return an empty operations list when nothing qualifies.\n\n"
        "Operation semantics:\n"
        "- op=add: `memory` holds the new fact (memory_id null).\n"
        "- op=update: `memory_id` is an existing id, `memory` the corrected fact.\n"
        "- op=delete: `memory_id` is the existing id to remove (memory null).\n"
        "- Optional `topics`: short tags like [\"location\", \"name\"].\n\n"
        f"<memories_to_capture>\n{capture_instructions}\n</memories_to_capture>\n\n"
        f"<existing_memories>\n{existing_lines}\n</existing_memories>\n\n"
        f"<user_message>\n{user_input}\n</user_message>"
    )


class CodexExecMemoryManager(MemoryManager):
    """MemoryManager whose extraction pass is one codex exec structured-output call."""

    def create_or_update_memories(  # type: ignore[override]
        self,
        messages,
        existing_memories,
        user_id: str,
        db,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        update_memories: bool = True,
        add_memories: bool = True,
        run_metrics=None,
    ) -> str:
        if len(messages) == 1:
            input_string = messages[0].get_content_string()
        else:
            input_string = ", ".join(
                m.get_content_string() for m in messages if m.role == "user" and m.content
            )
        if not (input_string or "").strip():
            return "no user input — no memory update"

        prompt = _extraction_prompt(self.memory_capture_instructions or "",
                                    existing_memories or [], input_string)
        import tempfile

        from bott.shared.model import resolve_model_id  # lazy: avoids import cycles
        try:
            with tempfile.TemporaryDirectory(prefix="bott-memory-") as cwd:
                result = run_codex_exec(
                    prompt, cwd=cwd, sandbox="read-only", ephemeral=True,
                    model_id=resolve_model_id("chat"),
                    output_schema=_OPS_SCHEMA,
                    timeout_s=config.codex_chat_timeout_s(),
                    binary=config.codex_cli_binary(),
                    user_id=user_id,
                )
        except CodexCliError as e:
            log.warning("memory capture skipped (codex exec failed): %s", e)
            return "memory capture skipped"

        ops = (result.data or {}).get("operations") or []
        tools = {fn.__name__: fn for fn in self._get_db_tools(
            user_id, db, input_string,
            enable_add_memory=add_memories,
            enable_update_memory=update_memories,
            enable_delete_memory=True,
            enable_clear_memory=False,
            agent_id=agent_id, team_id=team_id,
        )}
        applied: list[str] = []
        for op in ops:
            kind = (op or {}).get("op")
            try:
                if kind == "add" and "add_memory" in tools and op.get("memory"):
                    applied.append(tools["add_memory"](memory=op["memory"],
                                                       topics=op.get("topics")))
                elif kind == "update" and "update_memory" in tools and op.get("memory_id") \
                        and op.get("memory"):
                    applied.append(tools["update_memory"](memory_id=op["memory_id"],
                                                          memory=op["memory"],
                                                          topics=op.get("topics")))
                elif kind == "delete" and "delete_memory" in tools and op.get("memory_id"):
                    applied.append(tools["delete_memory"](memory_id=op["memory_id"]))
                else:
                    log.warning("memory op skipped (malformed or disabled): %r", op)
            except Exception as e:  # noqa: BLE001 — one bad op must not sink the rest
                log.warning("memory op failed: %r (%s)", op, e)
        if applied:
            self.memories_updated = True
        return f"applied {len(applied)} memory operation(s)" if applied else "no memory updates"

    async def acreate_or_update_memories(self, *args, **kwargs) -> str:  # type: ignore[override]
        # The extraction is a blocking subprocess + sync-db writes — run off the loop.
        return await asyncio.to_thread(self.create_or_update_memories, *args, **kwargs)
