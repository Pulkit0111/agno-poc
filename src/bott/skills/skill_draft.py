"""One-shot LLM drafting for console-created skills.

No Agent tools, no agentic loop — a single completion asked to emit strict JSON, parsed
with ONE retry on malformed output. `_complete` is a thin, deliberately monkeypatchable
seam: tests patch it directly rather than mocking Agno's Agent/model machinery (no live
network in tests). Mirrors the sync, Agent-wrapped, try/except-around-the-call shape used
by `agents/triage/triage.py`'s `_default_diagnose` — the closest existing one-shot-completion
precedent in this codebase (there is no call site that invokes a model object directly)."""

from __future__ import annotations

import json
import re

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_REQUIRED_KEYS = ("slug", "name", "description", "content")


def _complete(prompt: str) -> str:
    """Run one prompt through the chat-role model and return its raw text response."""
    from agno.agent import Agent

    from bott.shared.model import build_model

    agent = Agent(model=build_model("chat"))
    return (agent.run(prompt).content or "").strip()


def _extract_json(raw: str) -> dict:
    """Parse *raw* as JSON, tolerating a stray code fence or prose wrapper by falling back
    to the outermost {...} block if a direct parse fails."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_RE.search(raw)
        if not match:
            raise
        return json.loads(match.group(0))


def _build_prompt(what: str, when: str, feedback: str) -> str:
    prompt = f"""You are drafting a new reusable skill (a SKILL.md file) for the Bott AI \
agent, which runs in Slack and a web console.

What the skill should do: {what}
When it should trigger: {when}

Respond with STRICT JSON ONLY — no markdown code fences, no commentary before or after —
matching EXACTLY this shape:
{{"slug": "kebab-case-id", "name": "Human-Readable Title", "description": "one-line \
sentence on when to use this skill", "content": "the full skill body as markdown"}}

The "content" value must be a markdown document using this exact house style:

# <Human-Readable Title>

**When to use:** <one or two sentences describing the trigger>

## Steps
1. <first concrete step>
2. <next step>

## Done means
- <how to tell the skill succeeded>

Keep it concrete, actionable, and scoped to the request. Return ONLY the JSON object —
no other text."""
    if feedback.strip():
        prompt += (
            "\n\nThe previous draft didn't quite fit — revise per this feedback: "
            f"{feedback.strip()}"
        )
    return prompt


def draft_skill(what: str, when: str, feedback: str = "") -> dict:
    """Draft a skill via one model call. Returns {"slug","name","description","content"}.
    Saves nothing. Raises ValueError (callers should surface as a 502) if the model's
    output still isn't parseable JSON after one retry."""
    prompt = _build_prompt(what, when, feedback)
    raw = _complete(prompt)
    try:
        data = _extract_json(raw)
    except (json.JSONDecodeError, AttributeError):
        raw = _complete(
            prompt
            + "\n\nYour previous response was not valid JSON. Reply again with ONLY the "
            "raw JSON object — no fences, no explanation."
        )
        try:
            data = _extract_json(raw)
        except (json.JSONDecodeError, AttributeError) as e:
            raise ValueError(
                "The model didn't return usable JSON for the skill draft. Try again."
            ) from e
    if not isinstance(data, dict):
        raise ValueError("The drafted skill wasn't a JSON object.")
    missing = [k for k in _REQUIRED_KEYS if not data.get(k)]
    if missing:
        raise ValueError(f"The drafted skill is missing: {', '.join(missing)}.")
    return {k: data[k] for k in _REQUIRED_KEYS}
