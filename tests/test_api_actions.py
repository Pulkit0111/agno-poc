"""General guarded primitives — LLM composes, policy authorizes, executor acts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import bott.skills.connectors.actions as act


def _ctx(channel="C_CUR", thread="t1"):
    return SimpleNamespace(dependencies={"Slack channel_id": channel, "Slack thread_ts": thread},
                           user_id="me@x.com")


class _FakeSlack:
    def __init__(self):
        self.calls = []

    def api_call(self, method, params=None):
        self.calls.append((method, params or {}))
        return SimpleNamespace(data={"ok": True, "method": method})

    def chat_postMessage(self, **kw):
        self.calls.append(("chat.postMessage.card", kw))
        return {"ok": True}


def test_slack_read_executes(monkeypatch):
    fc = _FakeSlack()
    monkeypatch.setattr(act, "_slack_client", lambda: fc)
    out = act._run(_ctx(), "slack", "users.info", params_json='{"user": "U1"}')
    assert fc.calls[0][0] == "users.info"
    assert "ok" in out


def test_slack_safe_write_defaults_to_current_channel(monkeypatch):
    fc = _FakeSlack()
    monkeypatch.setattr(act, "_slack_client", lambda: fc)
    act._run(_ctx("C_HERE"), "slack", "chat.postMessage", params_json='{"text": "hi"}')
    method, params = fc.calls[0]
    assert method == "chat.postMessage" and params["channel"] == "C_HERE" and params["text"] == "hi"


def test_slack_gated_write_files_approval_not_execute(monkeypatch):
    fc = _FakeSlack()
    monkeypatch.setattr(act, "_slack_client", lambda: fc)
    created = {}

    def fake_create(user_id, action, summary, payload=None):
        created.update(user_id=user_id, action=action, summary=summary, payload=payload)
        return 77

    import bott.shared.approvals as approvals
    monkeypatch.setattr(approvals, "create_request", fake_create)
    out = act._run(_ctx(), "slack", "chat.delete", params_json='{"channel": "C1", "ts": "1.2"}',
                   summary="delete a message")
    assert created["action"] == "api:slack"
    assert json.loads(created["payload"])["method"] == "chat.delete"
    # The only Slack call is the approval CARD, not the delete itself.
    assert all(c[0] == "chat.postMessage.card" for c in fc.calls)
    assert "approve" in out.lower()


def test_slack_denied_method_refused(monkeypatch):
    fc = _FakeSlack()
    monkeypatch.setattr(act, "_slack_client", lambda: fc)
    out = act._run(_ctx(), "slack", "admin.users.remove")
    assert "won't" in out.lower() and not fc.calls


def test_invalid_params_json_friendly():
    out = act._run(_ctx(), "slack", "chat.postMessage", params_json="{not json")
    assert "couldn't parse" in out.lower()


def test_github_get_executes(monkeypatch):
    seen = {}

    class _R:
        content = b"{}"
        def raise_for_status(self): ...
        def json(self): return {"number": 5}

    import httpx
    monkeypatch.setattr(httpx, "request",
                        lambda method, url, **kw: seen.update(method=method, url=url) or _R())
    monkeypatch.setattr(act, "_github_token_for_path", lambda p: "tok")
    out = act._run(_ctx(), "github", "GET", path="/repos/o/r/pulls/5")
    assert seen["method"] == "GET" and seen["url"].endswith("/repos/o/r/pulls/5")
    assert "5" in out


def test_github_merge_gates(monkeypatch):
    monkeypatch.setenv("ALLOWED_POST_REPOS", "o/r")
    import bott.shared.approvals as approvals
    monkeypatch.setattr(approvals, "create_request", lambda **k: 9)
    monkeypatch.setattr(act, "_slack_client", lambda: _FakeSlack())
    out = act._run(_ctx(), "github", "PUT", path="/repos/o/r/pulls/3/merge", summary="merge PR 3")
    assert "approve" in out.lower()


def test_http_get_only(monkeypatch):
    class _R:
        headers = {"content-type": "text/html"}
        text = "<html>hello</html>"
        def raise_for_status(self): ...

    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _R())
    assert "hello" in act._run(_ctx(), "http", "GET", url="https://example.com/x")
    assert "won't" in act._run(_ctx(), "http", "POST", url="https://example.com/x").lower()


def test_dispatch_approved_api_executes_and_posts(monkeypatch):
    fc = _FakeSlack()
    monkeypatch.setattr(act, "_slack_client", lambda: fc)
    executed = {}
    monkeypatch.setattr(act, "execute_action", lambda p: executed.update(p) or "did it")
    import bott.shared.approvals as approvals
    row = {"status": "approved", "action": "api:slack",
           "payload": json.dumps({"system": "slack", "method": "chat.delete",
                                  "params": {"channel": "C1", "ts": "1.2"},
                                  "channel": "C_ORIG", "thread_ts": "t9"})}
    monkeypatch.setattr(approvals, "get_request", lambda i: row)
    act.dispatch_approved_api(4)
    assert executed["method"] == "chat.delete"
    assert fc.calls and fc.calls[0][1]["channel"] == "C_ORIG"


def test_dispatch_ignores_non_api_rows(monkeypatch):
    import bott.shared.approvals as approvals
    monkeypatch.setattr(approvals, "get_request",
                        lambda i: {"status": "approved", "action": "build:implement", "payload": "{}"})
    called = []
    monkeypatch.setattr(act, "execute_action", lambda p: called.append(p))
    act.dispatch_approved_api(1)
    assert not called


def test_actions_tools_exposed():
    names = {t.name for t in act.actions_tools()}
    assert {"slack_api", "github_api", "atlassian_api", "http_request"} <= names
