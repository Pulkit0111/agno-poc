"""Guard the bott-app worker wiring (app.main): the handler + queue primitives it needs
must stay importable. Regression guard — a refactor once let ruff strip these.
Updated in Phase-2-1B to use queue.py (Postgres) instead of the retired store.py."""

from __future__ import annotations


def test_worker_wiring_symbols_resolve(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)  # importable without a real token
    from bott.interfaces.slack_app import handle_task
    from bott.shared.persistence import queue

    assert callable(handle_task)
    assert callable(queue.init_queue)
    assert callable(queue.recover_orphans)
    assert callable(queue.worker_main)


def test_handle_task_accepts_dict_shape(monkeypatch, tmp_path):
    """handle_task must accept a dict job (not a Task object). Cheap early-return path:
    a 'rereview' job with a channel but no prior trace posts 'no prior review' and returns
    without hitting the model. Monkeypatch Slack calls to no-ops."""

    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from bott.shared import db
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()

    import bott.interfaces.slack_app as slack_app

    # Monkeypatch Slack API calls to no-ops so the test doesn't need real tokens.
    monkeypatch.setattr(slack_app, "_post", lambda *a, **kw: "0")
    monkeypatch.setattr(slack_app, "_react", lambda *a, **kw: None)

    job = {
        "id": 99,
        "kind": "rereview",
        "user_id": "U_TEST",
        "attempts": 0,
        "args": {
            "channel": "C_TEST",
            "thread_ts": "ts.001",
            "trigger_ts": "ts.001",
            "reply_text": "",
            "model_id": None,
        },
    }
    # Should not raise AttributeError (dict vs Task) and should return early
    # (latest_trace_for_thread returns None → posts "no prior review" message → returns).
    slack_app.handle_task(job)  # no exception = dict access works
