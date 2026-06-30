from types import SimpleNamespace

from bott.agents.build_fix import member


def test_start_build_enqueues_plan_job(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue",
                        lambda kind, args, user_id: calls.append((kind, args, user_id)) or 1)
    ctx = SimpleNamespace(user_id="alice@x.com", dependencies={"Slack channel_id": "C1", "Slack thread_ts": "t1"})
    msg = member.start_build("octo/repo#42", run_context=ctx)
    assert calls and calls[0][0] == "plan"
    kind, args, user_id = calls[0]
    assert args["owner"] == "octo" and args["repo"] == "repo" and args["issue"] == 42
    assert args["channel"] == "C1" and args["thread_ts"] == "t1"
    assert user_id == "alice@x.com"
    assert "queued" in msg.lower() or "plan" in msg.lower()


def test_build_tools_exposes_start_build():
    assert any(t.__name__ == "start_build" for t in member.build_tools())
