"""CodexExecChat — an Agno Model whose transport is one `codex exec` per turn.

Chat keeps the whole Agno wrapper (sessions, history windowing, memory recall, the Slack
interface) but the model call shells out to the official codex CLI on the org ChatGPT
subscription — the same single LLM path build/review/triage use. The Agno side sees a
text-only model (no Agno tool-calling): tools reach the model through bott's MCP server
instead (interfaces/mcp/), which codex connects to with a per-invocation signed bearer
ticket carrying the verified user identity from run_response. History arrives flattened
in the prompt each turn (Agno's num_history_runs window is the source of truth), so every
invocation is stateless (`--ephemeral`) and no codex session files accumulate.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator, Optional

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.response import ModelResponse

from bott.shared import config
from bott.shared.codex_cli import CodexAuthError, CodexCliError, CodexQuotaError, run_codex_exec
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.codex_exec_model")


def _flatten_messages(messages) -> str:
    """System message(s) verbatim first, then role-tagged turns — the reference-deployment
    prompt-replay shape. Tool messages can't occur (this model never emits tool calls)."""
    parts: list[str] = []
    for m in messages or []:
        role = getattr(m, "role", "user") or "user"
        content = m.get_content_string() if hasattr(m, "get_content_string") else str(
            getattr(m, "content", "") or "")
        if not content:
            continue
        if role == "system":
            parts.append(content)
        elif role in ("user", "assistant", "developer"):
            parts.append(f"[{role}] {content}")
    return "\n\n".join(parts)


def _resolve_output(response_format) -> tuple[Optional[dict], Optional[str]]:
    """Map Agno's response_format to (codex --output-schema dict, extra prompt line)."""
    if response_format is None:
        return None, None
    if isinstance(response_format, dict):
        if response_format.get("type") == "json_object":
            return None, "Respond with a single valid JSON object, no prose, no fences."
        if response_format.get("type") == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema")
            return schema, None
        return None, None
    if isinstance(response_format, type) and hasattr(response_format, "model_json_schema"):
        return response_format.model_json_schema(), None
    return None, None


def _record_usage(user_id, model_id: str, tokens_used: int) -> None:
    try:
        from bott.shared.codex_usage import record_call
        record_call(user_id, model_id, tokens_used)
    except Exception:  # noqa: BLE001 — visibility must never break the call it's watching
        pass


@dataclass
class CodexExecChat(Model):
    """Text-only Agno model backed by `codex exec` (+ bott's MCP tools when the run has a
    verified user identity)."""

    name: Optional[str] = "CodexExec"
    provider: Optional[str] = "codex"

    def invoke(self, messages=None, assistant_message=None, response_format=None,
               tools=None, tool_choice=None, run_response=None,
               compress_tool_results=False, **_ignored) -> ModelResponse:  # type: ignore[override]
        user_id = getattr(run_response, "user_id", None)
        session_id = getattr(run_response, "session_id", None) or ""

        prompt = _flatten_messages(messages)
        output_schema, extra_line = _resolve_output(response_format)
        if extra_line:
            prompt = f"{prompt}\n\n{extra_line}"

        extra_config: dict = {}
        extra_env: dict = {}
        if user_id:
            # Wire bott's MCP tool server into codex's own loop, authenticated with a
            # one-turn ticket minted from the VERIFIED identity (never model text).
            from bott.interfaces.mcp.tickets import make_ticket
            extra_config = {
                "mcp_servers.bott.url": f'"{config.bott_mcp_url()}"',
                "mcp_servers.bott.bearer_token_env_var": '"BOTT_MCP_TICKET"',
            }
            extra_env = {"BOTT_MCP_TICKET": make_ticket(user_id, session_id)}

        metrics = getattr(assistant_message, "metrics", None)
        if metrics is not None:
            metrics.start_timer()
        try:
            with tempfile.TemporaryDirectory(prefix="bott-chat-") as cwd:
                result = run_codex_exec(
                    prompt,
                    cwd=cwd,
                    sandbox="read-only",
                    ephemeral=True,
                    model_id=self.id,
                    output_schema=output_schema,
                    timeout_s=config.codex_chat_timeout_s(),
                    binary=config.codex_cli_binary(),
                    extra_config=extra_config,
                    extra_env=extra_env,
                    user_id=user_id,
                )
        except CodexQuotaError as e:
            raise ModelProviderError(
                message="The org ChatGPT subscription hit its usage limit — try again "
                        f"later. ({e})",
                status_code=429, model_name=self.name, model_id=self.id) from e
        except CodexAuthError as e:
            # Non-retryable (Agno treats 401 as terminal): a dead login won't heal between
            # attempts — alert the admins once (throttled) and fail this request honestly.
            try:
                from bott.shared.alerts import alert_admins_throttled
                alert_admins_throttled(
                    "codex-disconnected",
                    "Bott's shared Codex (ChatGPT) login is broken or missing — every "
                    "model call will fail until an admin reconnects it (console → Models "
                    f"→ Connect ChatGPT, or `codex login`). First error: {str(e)[:300]}")
            except Exception:  # noqa: BLE001 — alerting must not mask the real error
                pass
            raise ModelProviderError(
                message="The org ChatGPT (codex) login is broken or missing — an admin "
                        "needs to reconnect it from the console (Models → Connect ChatGPT).",
                status_code=401, model_name=self.name, model_id=self.id) from e
        except CodexCliError as e:
            raise ModelProviderError(message=str(e), status_code=502,
                                     model_name=self.name, model_id=self.id) from e
        finally:
            if metrics is not None:
                metrics.stop_timer()

        _record_usage(user_id, self.id, result.tokens_used)
        return ModelResponse(content=result.text)

    async def ainvoke(self, messages=None, assistant_message=None, response_format=None,
                      tools=None, tool_choice=None, run_response=None,
                      compress_tool_results=False, **_ignored) -> ModelResponse:  # type: ignore[override]
        # The subprocess call is blocking — keep it off the event loop.
        return await asyncio.to_thread(
            self.invoke, messages=messages, assistant_message=assistant_message,
            response_format=response_format, tools=tools, tool_choice=tool_choice,
            run_response=run_response, compress_tool_results=compress_tool_results)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:  # type: ignore[override]
        # codex exec has no incremental output through --output-last-message; emit the
        # final response as one terminal chunk (the Slack interface runs streaming=False).
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:  # type: ignore[override]
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        # invoke() already returns a fully-formed ModelResponse; the base class hands it
        # straight to _populate_assistant_message and never calls this.
        raise NotImplementedError("CodexExecChat.invoke returns ModelResponse directly")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError("CodexExecChat streams a single terminal chunk")
