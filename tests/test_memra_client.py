"""Deterministic (no-network) tests for the Memra MCP client parsing/retry logic."""

from __future__ import annotations

import json

from bott.shared.context.memra import MemraClient, make_memra_tools


class _FakeResp:
    def __init__(self, body, *, sse=False, status=200):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": "text/event-stream" if sse else "application/json"}

    @property
    def text(self):
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body)

    def json(self):
        return self._body


def _tool_result(obj_text: str):
    return {"result": {"content": [{"type": "text", "text": obj_text}]}}


def _client(monkeypatch):
    c = MemraClient(client_id="x", client_secret="y", token_endpoint="t", mcp_endpoint="m")
    monkeypatch.setattr(c, "_ensure_token", lambda: "tok")
    monkeypatch.setattr(c, "_ensure_session", lambda: None)
    return c


def test_parse_json_and_sse():
    assert MemraClient._parse(_FakeResp({"a": 1})) == {"a": 1}
    sse = 'event: message\ndata: {"jsonrpc":"2.0","result":42}\n\n'
    assert MemraClient._parse(_FakeResp(sse, sse=True)) == {"jsonrpc": "2.0", "result": 42}


def test_call_tool_decodes_json_payload(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(c, "_rpc", lambda payload: _FakeResp(_tool_result('{"active_total": 86}')))
    assert c.engagements_at_risk() == {"active_total": 86}


def test_call_tool_returns_raw_text_when_not_json(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(c, "_rpc", lambda payload: _FakeResp(_tool_result("just text")))
    assert c.ask_context("hi") == "just text"


def test_make_memra_tools_exposes_read_only_set(monkeypatch):
    c = _client(monkeypatch)
    names = {t.__name__ for t in make_memra_tools(c)}
    assert "memra_ask_context" in names and "memra_resolve_channel_entity" in names
    assert not any("propose_alias" in n for n in names)  # write tool not exposed
