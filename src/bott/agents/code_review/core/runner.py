"""Run the PR review through `codex exec` and map its structured output into the
AgentRunResult the gate + renderer consume. Codex's own tool use inside the subprocess
isn't traceable from here, so engagement_observable=False and the verdict gate relaxes
its tool-call cross-checks (see verdict_gate.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from bott.shared.codex_cli import CodexCliError, run_codex_exec
from bott.shared.config import (
    DEFAULT_MODEL,
    Budget,
    codex_cli_binary,
    codex_cli_timeout_s,
)
from bott.shared.model import _review_anti_affinity, resolve_model_id, resolve_provider

from ..agent.prompt import PROMPT_VERSION
from ..github.fetch_essentials import PrEssentials
from .models import ReviewOutput
from .types import ToolCallTrace
from .verdict_gate import Termination

@dataclass
class AgentRunResult:
    output: Optional[ReviewOutput]
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    termination: Termination = "no_submission"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Optional[float] = None
    error: Optional[str] = None
    prompt_version: str = PROMPT_VERSION
    model_id: str = DEFAULT_MODEL
    engagement_observable: bool = True


def _run_review_agent_cli(
    essentials: PrEssentials,
    clone_path: str,
    *,
    project_addendum: Optional[str],
    prior_review: Optional[str],
) -> AgentRunResult:
    """Review via `codex exec` instead of Agno's tool-calling loop. Codex's own tool use
    inside the subprocess isn't traceable from here, so tool_calls is always empty and
    engagement_observable=False — the verdict gate (verdict_gate.py) relaxes its
    tool-call-cross-check preconditions accordingly.

    The model is resolved the SAME way the Agno path resolves it (resolve_model_id +
    anti-affinity), NOT taken from the caller's `model_id` argument — that argument is only
    a cost-calculation label upstream (see slack_app.py's `review_model = a.get("model_id")
    or bott_model()`), never the actual selector. Skipping this resolution would silently
    let every CLI-exec review run on the CLI's own default model, defeating both bott's
    per-role model config AND the anti-affinity invariant (reviewer != author model)."""
    from bott.agents.code_review.agent.prompt import build_cli_review_prompt

    provider = resolve_provider("review")
    resolved_model_id = _review_anti_affinity(resolve_model_id("review"), provider)

    prompt = build_cli_review_prompt(essentials, project_addendum, prior_review)
    schema = ReviewOutput.model_json_schema()
    try:
        result = run_codex_exec(
            prompt, cwd=clone_path, sandbox="read-only", model_id=resolved_model_id,
            output_schema=schema, timeout_s=codex_cli_timeout_s(),
            binary=codex_cli_binary(),
        )
    except CodexCliError as e:
        return AgentRunResult(output=None, termination="model_error", error=str(e),
                              model_id=resolved_model_id, engagement_observable=False)

    if result.data is None:
        return AgentRunResult(output=None, termination="no_submission",
                              error="codex exec produced no structured output",
                              model_id=resolved_model_id, engagement_observable=False)
    try:
        output = ReviewOutput(**result.data)
    except Exception as e:  # pydantic ValidationError
        return AgentRunResult(output=None, termination="no_submission",
                              error=f"codex exec output failed schema validation: {e}",
                              model_id=resolved_model_id, engagement_observable=False)

    return AgentRunResult(
        output=output, tool_calls=[], termination="natural",
        total_tokens=result.tokens_used,
        # cost_usd left None — the CLI's stderr only reports a combined token count, not
        # the input/output split calculate_cost() needs.
        model_id=resolved_model_id, engagement_observable=False,
    )


def run_review_agent(
    essentials: PrEssentials,
    clone_path: str,
    *,
    model_id: str = DEFAULT_MODEL,
    budget: Optional[Budget] = None,
    project_addendum: Optional[str] = None,
    prior_review: Optional[str] = None,
    use_json_mode: bool = False,
    on_tool: Optional[Callable[[str, dict], None]] = None,
) -> AgentRunResult:
    """Run the PR review through `codex exec` (the only execution path — every LLM call in
    bott rides the org ChatGPT subscription via the official CLI).

    `model_id`, `budget`, `use_json_mode` and `on_tool` are accepted for caller
    compatibility but unused: the CLI resolves its own model (resolve_model_id +
    anti-affinity), runs its own internal loop (no per-tool progress to hook), and
    enforces structured output via --output-schema."""
    del model_id, budget, use_json_mode, on_tool  # caller-compat only (see docstring)
    return _run_review_agent_cli(
        essentials, clone_path,
        project_addendum=project_addendum, prior_review=prior_review,
    )
