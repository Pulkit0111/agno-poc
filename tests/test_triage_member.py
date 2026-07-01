from types import SimpleNamespace

from bott.agents.triage import member


def test_start_triage_enqueues(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue",
                        lambda kind, args, user_id: calls.append((kind, args, user_id)) or 1)
    ctx = SimpleNamespace(user_id="alice@x.com",
                          dependencies={"Slack channel_id": "C1", "Slack thread_ts": "t1"})
    msg = member.start_triage("12345", "axelerant/foo", run_context=ctx)
    assert calls and calls[0][0] == "triage"
    _, args, user_id = calls[0]
    assert args["sentry_issue_id"] == "12345"
    assert args["owner"] == "axelerant" and args["name"] == "foo"
    assert args["channel"] == "C1" and args["thread_ts"] == "t1"
    assert user_id == "alice@x.com"
    assert "12345" in msg


def test_start_triage_rejects_bad_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue", lambda *a, **k: calls.append(a) or 1)
    out = member.start_triage("12345", "not-a-repo")
    assert "owner/name" in out.lower() or "repo" in out.lower()
    assert not calls  # nothing enqueued


def test_triage_tools_exposes_start_triage():
    assert any(getattr(t, "__name__", "") == "start_triage" for t in member.triage_tools())
