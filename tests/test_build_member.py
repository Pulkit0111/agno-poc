from types import SimpleNamespace

from bott.agents.build_fix import member


def test_start_build_enqueues_plan_job(monkeypatch):
    monkeypatch.delenv("ALLOWED_POST_REPOS", raising=False)  # empty allowlist → gate is lenient
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


def test_start_build_uses_explicit_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue",
                        lambda kind, args, user_id: calls.append((kind, args)) or 1)
    monkeypatch.setenv("ALLOWED_POST_REPOS", "pulkit0111/moodflix")
    ctx = SimpleNamespace(user_id="a@x.com", dependencies={"Slack channel_id": "C1", "Slack thread_ts": "t1"})
    # The change description mentions "docs/auth" — the explicit repo must win, not the phrase.
    msg = member.start_build("Fix the admin sync docs/auth mismatch",
                             repo="pulkit0111/moodflix", run_context=ctx)
    assert calls and calls[0][1]["owner"] == "pulkit0111" and calls[0][1]["repo"] == "moodflix"
    assert "plan" in msg.lower()


def test_start_build_asks_when_no_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue", lambda *a, **k: calls.append(a) or 1)
    monkeypatch.setenv("ALLOWED_POST_REPOS", "pulkit0111/moodflix")
    ctx = SimpleNamespace(user_id="a@x.com", dependencies={})
    msg = member.start_build("please add a health check endpoint", run_context=ctx)
    assert not calls  # nothing enqueued — no repo to build on
    assert "which repo" in msg.lower()


def test_start_build_refuses_non_allowlisted_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue", lambda *a, **k: calls.append(a) or 1)
    monkeypatch.setenv("ALLOWED_POST_REPOS", "pulkit0111/moodflix")
    ctx = SimpleNamespace(user_id="a@x.com", dependencies={})
    msg = member.start_build("fix a bug", repo="some/random-repo", run_context=ctx)
    assert not calls  # refused up front — no "On it" then a background refusal
    assert "allow" in msg.lower()


def test_build_tools_exposes_start_build():
    assert any(t.__name__ == "start_build" for t in member.build_tools())
