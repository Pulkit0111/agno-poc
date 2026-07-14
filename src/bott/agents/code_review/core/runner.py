"""Build and run the Agno review agent — port of agent.ts (runReviewAgent).

Runs the agent programmatically (agent.run), maps the RunOutput into an
AgentRunResult the gate + renderer consume: the recorded tool calls, token/cost
usage, and a termination classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agno.agent import Agent

from bott.shared.codex_cli import CodexCliError, run_codex_exec
from bott.shared.config import (
    DEFAULT_MODEL,
    Budget,
    calculate_cost,
    codex_cli_binary,
    codex_cli_enabled,
    codex_cli_timeout_s,
    review_temperature,
)
from bott.shared.model import _review_anti_affinity, build_model, resolve_model_id, resolve_provider

from ..agent.prompt import PROMPT_VERSION, build_system_prompt
from ..agent.tools import ReviewTools
from ..github.fetch_essentials import PrEssentials
from .models import ReviewOutput
from .types import ToolCallTrace
from .verdict_gate import Termination

USER_TRIGGER = (
    "Review the pull request described in your instructions. Investigate with your "
    "tools, then produce your final structured review as a single JSON object matching "
    "the required schema. (The literal word 'json' here also satisfies the Codex/Responses "
    "json_object requirement.)"
)


def _classify_termination(status_str: str, n_tool_calls: int, has_output: bool,
                          max_tool_calls: int) -> Termination:
    """Map a finished run to a termination reason. `status_str` is str(run.status): Agno's
    RunStatus.error renders as "RunStatus.error" (value "ERROR"), so match "error"
    case-insensitively — a strict ``== "error"`` misses it and a real model failure then
    masquerades as no_submission (the misleading "PR may be large" message)."""
    if "error" in (status_str or "").lower():
        return "model_error"
    if n_tool_calls >= max_tool_calls:
        return "budget"
    if has_output:
        return "natural"
    return "no_submission"


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
    budget = budget or Budget()
    if codex_cli_enabled() and resolve_provider("review") == "codex":
        return _run_review_agent_cli(
            essentials, clone_path,
            project_addendum=project_addendum, prior_review=prior_review,
        )
    system_prompt = build_system_prompt(essentials, project_addendum, prior_review)

    def _progress_hook(function_name, function_call, arguments):
        # Fire a progress callback before each tool runs, then execute it.
        if on_tool:
            try:
                on_tool(function_name, dict(arguments or {}))
            except Exception:
                pass
        return function_call(**arguments)

    agent = Agent(
        # Survive per-minute TPM limits (low account tier): the agentic loop sends a
        # large growing context, so transient 429s are expected.
        # "review" role — the gateway enforces anti-affinity with the "build" role, so the
        # model reviewing a PR is never the model that wrote it (no shared blind spots).
        model=build_model(
            "review",
            retries=5, delay_between_retries=3,
            # Optional reproducibility knob; only passed when explicitly set (gpt-5 reasoning
            # models reject temperature != 1, so default is to omit it entirely).
            **({"temperature": review_temperature()} if review_temperature() is not None else {}),
        ),
        tools=[ReviewTools(clone_path, essentials)],
        system_message=system_prompt,
        output_schema=ReviewOutput,
        use_json_mode=(use_json_mode or resolve_provider("review") == "codex"),
        tool_call_limit=budget.max_tool_calls,
        tool_hooks=[_progress_hook] if on_tool else None,
        telemetry=False,
        markdown=False,
    )

    try:
        run = agent.run(USER_TRIGGER)
    except Exception as e:  # model/transport error
        return AgentRunResult(
            output=None, termination="model_error", error=str(e), model_id=model_id
        )

    tool_calls = [
        ToolCallTrace(
            name=t.tool_name or "",
            args=dict(t.tool_args or {}),
            result_summary=str(t.result)[:500] if t.result is not None else "",
        )
        for t in (run.tools or [])
    ]

    content = run.content
    output = content if isinstance(content, ReviewOutput) else None

    m = run.metrics
    status = str(getattr(run, "status", "") or "")

    termination = _classify_termination(status, len(tool_calls), output is not None,
                                        budget.max_tool_calls)
    run_error: Optional[str] = None
    if termination == "model_error":
        # Surface the real cause (a 400/json error, a rate limit, ...) instead of dropping it —
        # slack_app logs result.run.error, so a hidden None is what made failures opaque.
        run_error = (str(getattr(run, "content", "") or "").strip()
                     or "the model returned an error before producing a verdict")

    input_tokens = getattr(m, "input_tokens", 0) or 0
    output_tokens = getattr(m, "output_tokens", 0) or 0
    cache_read = getattr(m, "cache_read_tokens", 0) or 0
    cache_write = getattr(m, "cache_write_tokens", 0) or 0
    cost = getattr(m, "cost", None)
    if cost is None:
        cost = calculate_cost(model_id, input_tokens, output_tokens, cache_read, cache_write)

    return AgentRunResult(
        output=output,
        tool_calls=tool_calls,
        termination=termination,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=getattr(m, "total_tokens", 0) or 0,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=cost,
        error=run_error,
        model_id=model_id,
    )
