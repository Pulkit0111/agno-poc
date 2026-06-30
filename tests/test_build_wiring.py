"""Task 8: wire-up tests — dispatch_approved_build in the Slack Home router
and _run_implement implement-branch behavior.
"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

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


# ── _run_implement implement-branch behavior ──────────────────────────────────
# We test the extracted _run_implement helper directly (lowest-risk approach —
# handle_task is too entangled with Slack/reaction plumbing to test offline).
# The lazy imports of implement_task + result_blocks inside _run_implement are
# intercepted via sys.modules so no network/token calls are made.

def _make_fake_pipeline_modules(monkeypatch, *, implement_side_effect=None, result=None):
    """Inject fake bott.agents.build_fix.{pipeline,rendering} into sys.modules so
    _run_implement's lazy 'from ... import ...' picks them up."""
    fake_result = result or SimpleNamespace(opened_pr=True, pr_url="https://github.com/o/r/pull/1",
                                             tests="green", note="ok", diff_summary="diff")
    if implement_side_effect is not None:
        impl_mock = MagicMock(side_effect=implement_side_effect)
    else:
        impl_mock = MagicMock(return_value=fake_result)

    fake_pipeline = MagicMock()
    fake_pipeline.implement_task = impl_mock

    fake_rendering = MagicMock()
    fake_rendering.result_blocks = MagicMock(return_value=(
        [{"type": "section"}], "pr opened"
    ))

    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.pipeline", fake_pipeline)
    monkeypatch.setitem(sys.modules, "bott.agents.build_fix.rendering", fake_rendering)
    return impl_mock, fake_rendering.result_blocks


def test_run_implement_no_token_posts_no_access_and_does_not_call_implement(monkeypatch):
    """When app_token_for returns None, _run_implement posts the 'needs write access' message
    and does NOT call implement_task at all."""
    import bott.interfaces.slack_app as app_mod

    impl_mock, _ = _make_fake_pipeline_modules(monkeypatch)
    monkeypatch.setattr(app_mod, "app_token_for", lambda owner, name: None)

    posted = []
    monkeypatch.setattr(app_mod, "_post",
                        lambda ch, ts, blocks, fallback: posted.append((ch, ts, blocks, fallback)))

    app_mod._run_implement(
        {"owner": "myorg", "name": "myrepo", "plan_text": "add tests"},
        channel="C123", thread_ts="1234.5678",
    )

    # Must not have called the expensive implement_task
    impl_mock.assert_not_called()
    # Must have posted exactly one message containing the "write access" language
    assert len(posted) == 1
    _ch, _ts, blocks, fallback = posted[0]
    assert _ch == "C123"
    assert "write access" in fallback.lower() or any(
        "write access" in str(b) for b in blocks
    )


def test_run_implement_exception_posts_failure_and_does_not_propagate(monkeypatch):
    """When implement_task raises, _run_implement logs + posts a failure message and
    returns normally (so the worker marks the job done and does not retry)."""
    import bott.interfaces.slack_app as app_mod

    impl_mock, _ = _make_fake_pipeline_modules(
        monkeypatch, implement_side_effect=RuntimeError("git push failed: ***")
    )
    monkeypatch.setattr(app_mod, "app_token_for", lambda owner, name: "ghs_faketoken")

    posted = []
    monkeypatch.setattr(app_mod, "_post",
                        lambda ch, ts, blocks, fallback: posted.append((ch, ts, blocks, fallback)))

    # Must return normally — not raise
    app_mod._run_implement(
        {"owner": "myorg", "name": "myrepo", "plan_text": "add tests"},
        channel="C123", thread_ts="1234.5678",
    )

    # implement_task was called
    impl_mock.assert_called_once()
    # A failure message was posted
    assert len(posted) == 1
    _ch, _ts, blocks, fallback = posted[0]
    assert _ch == "C123"
    assert "couldn't complete" in fallback.lower() or any(
        "couldn't complete" in str(b) for b in blocks
    )
