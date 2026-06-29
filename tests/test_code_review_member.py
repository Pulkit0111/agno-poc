from unittest.mock import patch

from bott.agents.code_review import member


def test_start_review_uses_contextvar_target():
    token = member.set_review_target(
        {"channel": "C1", "thread_ts": "111.0", "trigger_ts": "111.0"}
    )
    try:
        with patch.object(member.queue, "enqueue") as enq:
            msg = member.start_review("owner/repo#7")
        assert "owner/repo#7" in msg
        kind, args = enq.call_args[0]
        assert kind == "review"
        assert args["channel"] == "C1" and args["number"] == 7
    finally:
        member.reset_review_target(token)


def test_start_review_without_target_queues_no_channel():
    with patch.object(member.queue, "enqueue") as enq:
        member.start_review("https://github.com/o/r/pull/9")
    _, args = enq.call_args[0]
    assert args["channel"] is None and args["number"] == 9


def test_start_rereview_requires_thread():
    assert "only work in a Slack thread" in member.start_rereview("fix it")
