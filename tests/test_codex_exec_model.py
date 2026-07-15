"""CodexExecChat — the Agno model whose transport is `codex exec` (no real binary)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from bott.interfaces.mcp.tickets import verify_ticket
from bott.shared import codex_exec_model as cem
from bott.shared.codex_cli import CodexCliError, CodexExecResult, CodexQuotaError
from bott.shared.secrets import generate_key


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BOTT_SECRET_KEY", generate_key())


def _run_response(user_id="u@x.com", session_id="s1"):
    return SimpleNamespace(user_id=user_id, session_id=session_id, metrics=None)


def _msgs():
    return [Message(role="system", content="SYSTEM RULES"),
            Message(role="user", content="hi there")]


def test_invoke_flattens_and_returns_content(monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        captured.update(kw)
        return CodexExecResult(text="hello!", data=None, tokens_used=7)

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    model = cem.CodexExecChat(id="gpt-5.5")
    out = model.invoke(messages=_msgs(), assistant_message=Message(role="assistant"),
                       run_response=_run_response())
    assert out.content == "hello!"
    assert captured["prompt"].startswith("SYSTEM RULES")
    assert "[user] hi there" in captured["prompt"]
    assert captured["sandbox"] == "read-only"
    assert captured["ephemeral"] is True
    assert captured["model_id"] == "gpt-5.5"
    assert captured["user_id"] == "u@x.com"


def test_invoke_wires_mcp_with_verified_ticket(monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured.update(kw)
        return CodexExecResult(text="ok", data=None, tokens_used=1)

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    cem.CodexExecChat(id="gpt-5.5").invoke(
        messages=_msgs(), assistant_message=Message(role="assistant"),
        run_response=_run_response(user_id="alice@x.com", session_id="thread-9"))
    cfg = captured["extra_config"]
    assert cfg["mcp_servers.bott.bearer_token_env_var"] == '"BOTT_MCP_TICKET"'
    assert cfg["mcp_servers.bott.url"].startswith('"http')
    ident = verify_ticket(captured["extra_env"]["BOTT_MCP_TICKET"])
    assert ident.user_id == "alice@x.com"
    assert ident.session_id == "thread-9"


def test_invoke_without_identity_runs_toolless(monkeypatch):
    """No verified user (memory jobs, scripts) → no MCP wiring, no ticket."""
    captured = {}

    def fake(prompt, **kw):
        captured.update(kw)
        return CodexExecResult(text="ok", data=None, tokens_used=1)

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    cem.CodexExecChat(id="gpt-5.5").invoke(
        messages=_msgs(), assistant_message=Message(role="assistant"), run_response=None)
    # No MCP wiring and no ticket — only the always-on built-in-tool lockdown remains.
    assert "mcp_servers.bott.url" not in captured["extra_config"]
    assert captured["extra_config"]["features.shell_tool"] == "false"
    assert captured["extra_env"] == {}


def test_quota_error_maps_to_429(monkeypatch):
    def fake(prompt, **kw):
        raise CodexQuotaError("usage limit")

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    with pytest.raises(ModelProviderError) as ei:
        cem.CodexExecChat(id="m").invoke(messages=_msgs(),
                                         assistant_message=Message(role="assistant"))
    assert ei.value.status_code == 429
    assert "usage limit" in str(ei.value.message)


def test_cli_error_maps_to_502(monkeypatch):
    def fake(prompt, **kw):
        raise CodexCliError("exit 1: sandbox exploded")

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    with pytest.raises(ModelProviderError) as ei:
        cem.CodexExecChat(id="m").invoke(messages=_msgs(),
                                         assistant_message=Message(role="assistant"))
    assert ei.value.status_code == 502


def test_json_object_mode_appends_instruction(monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        captured.update(kw)
        return CodexExecResult(text="{}", data=None, tokens_used=1)

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    cem.CodexExecChat(id="m").invoke(messages=_msgs(),
                                     assistant_message=Message(role="assistant"),
                                     response_format={"type": "json_object"})
    assert "valid JSON object" in captured["prompt"]
    assert captured["output_schema"] is None


def test_pydantic_response_format_becomes_output_schema(monkeypatch):
    from pydantic import BaseModel

    class Shape(BaseModel):
        answer: str

    captured = {}

    def fake(prompt, **kw):
        captured.update(kw)
        return CodexExecResult(text='{"answer":"x"}', data={"answer": "x"}, tokens_used=1)

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    cem.CodexExecChat(id="m").invoke(messages=_msgs(),
                                     assistant_message=Message(role="assistant"),
                                     response_format=Shape)
    assert captured["output_schema"]["properties"]["answer"]["type"] == "string"


def test_agno_agent_end_to_end_with_fake_runner(monkeypatch):
    """The full Agno loop accepts CodexExecChat: Agent.run returns the codex text."""
    from agno.agent import Agent

    monkeypatch.setattr(cem, "run_codex_exec",
                        lambda prompt, **kw: CodexExecResult(text="agent says hi",
                                                             data=None, tokens_used=2))
    agent = Agent(model=cem.CodexExecChat(id="gpt-5.5"), telemetry=False, markdown=False)
    run = agent.run("hello")
    assert run.content == "agent says hi"


def test_build_model_chat_returns_codex_exec_chat(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    from bott.shared import model as model_mod
    monkeypatch.setattr(model_mod, "_setting", lambda key: None)  # ignore local dev DB overrides
    m = model_mod.build_model("chat")
    assert isinstance(m, cem.CodexExecChat)
    assert m.retries == 3


def test_chat_disables_codex_builtin_tools_and_bypasses_sandbox(monkeypatch):
    """Chat's codex exec must (a) bypass the sandbox/approval layer — otherwise every MCP
    tool call is auto-cancelled — and (b) disable codex's own shell + web search so the
    bypass exposes nothing beyond bott's ticket-scoped MCP tools."""
    captured = {}

    def fake(prompt, **kw):
        captured.update(kw)
        return CodexExecResult(text="ok", data=None, tokens_used=1)

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    cem.CodexExecChat(id="gpt-5.5").invoke(
        messages=_msgs(), assistant_message=Message(role="assistant"),
        run_response=_run_response())
    assert captured["bypass_sandbox"] is True
    assert captured["extra_config"]["features.shell_tool"] == "false"
    assert captured["extra_config"]["tools.web_search"] == "false"
