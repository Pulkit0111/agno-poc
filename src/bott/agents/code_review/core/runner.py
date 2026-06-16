"""Build and run the Agno review agent — port of agent.ts (runReviewAgent).

Runs the agent programmatically (agent.run), maps the RunOutput into an
AgentRunResult the gate + renderer consume: the recorded tool calls, token/cost
usage, and a termination classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agno.agent import Agent

from bott.shared.config import DEFAULT_MODEL, Budget, calculate_cost, model_api_key, model_base_url
from bott.shared.model import build_model

from ..agent.prompt import PROMPT_VERSION, build_system_prompt
from ..agent.tools import ReviewTools
from ..github.fetch_essentials import PrEssentials
from .models import ReviewOutput
from .types import ToolCallTrace
from .verdict_gate import Termination

USER_TRIGGER = (
    "Review the pull request described in your instructions. Investigate with your "
    "tools, then produce your final structured review."
)


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
        model=build_model(
            model_id, base_url=model_base_url(), api_key=model_api_key(),
            retries=5, delay_between_retries=3,
        ),
        tools=[ReviewTools(clone_path, essentials)],
        system_message=system_prompt,
        output_schema=ReviewOutput,
        use_json_mode=use_json_mode,
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

    if status == "error":
        termination: Termination = "model_error"
    elif len(tool_calls) >= budget.max_tool_calls:
        # tool_call_limit reached — treat as budget exhaustion (gate downgrades approve).
        termination = "budget"
    elif output is not None:
        termination = "natural"
    else:
        termination = "no_submission"

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
        error=None,
        model_id=model_id,
    )
