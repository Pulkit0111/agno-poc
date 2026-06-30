"""Task 8: wire-up tests — dispatch_approved_build in the Slack Home router."""
import json
from types import SimpleNamespace

import bott.interfaces.slack_home.router as router_mod


def test_approved_build_payload_enqueues_implement(monkeypatch):
    # Simulate the approve-handler dispatch helper: an approved build:* request enqueues implement.
    enq = []
    monkeypatch.setattr(router_mod, "queue",
                        SimpleNamespace(enqueue=lambda *a, **k: enq.append((a, k))))
    monkeypatch.setattr(router_mod, "approvals", SimpleNamespace(
        get_request=lambda aid: {"id": aid, "action": "build:implement", "status": "approved",
                                 "user_id": "alice@x.com",
                                 "payload": json.dumps({"owner": "o", "name": "r", "plan_text": "x",
                                                         "channel": "C", "thread_ts": "t"})}))
    router_mod.dispatch_approved_build(7)
    assert enq
    args, kwargs = enq[0]
    assert args[0] == "implement"
    assert args[1]["owner"] == "o"
    assert kwargs["user_id"] == "alice@x.com"
    assert kwargs["dedup_key"] == "implement:7"


def test_dispatch_ignores_non_build_or_unapproved(monkeypatch):
    enq = []
    monkeypatch.setattr(router_mod, "queue",
                        SimpleNamespace(enqueue=lambda *a, **k: enq.append(a)))
    monkeypatch.setattr(router_mod, "approvals", SimpleNamespace(
        get_request=lambda aid: {"id": aid, "action": "build:implement", "status": "dismissed",
                                 "user_id": "u", "payload": "{}"}))
    router_mod.dispatch_approved_build(7)
    assert not enq  # dismissed → nothing enqueued


def test_dispatch_ignores_approved_non_build_action(monkeypatch):
    enq = []
    monkeypatch.setattr(router_mod, "queue",
                        SimpleNamespace(enqueue=lambda *a, **k: enq.append(a)))
    monkeypatch.setattr(router_mod, "approvals", SimpleNamespace(
        get_request=lambda aid: {"id": aid, "action": "review:something", "status": "approved",
                                 "user_id": "u", "payload": "{}"}))
    router_mod.dispatch_approved_build(7)
    assert not enq  # approved but NOT a build:* action → nothing enqueued


def test_dispatch_ignores_missing_row(monkeypatch):
    enq = []
    monkeypatch.setattr(router_mod, "queue",
                        SimpleNamespace(enqueue=lambda *a, **k: enq.append(a)))
    monkeypatch.setattr(router_mod, "approvals", SimpleNamespace(get_request=lambda aid: None))
    router_mod.dispatch_approved_build(7)
    assert not enq  # missing approval row → nothing enqueued
