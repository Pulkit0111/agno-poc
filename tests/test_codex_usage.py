"""Usage ledger for the shared org Codex account — the only visibility an admin has into
how close the org is to a rate/usage ceiling, since one account carries all of Bott's
traffic."""

from __future__ import annotations

import time

import pytest

from bott.shared import codex_usage, db


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "cu.db"))
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    yield


def test_empty_ledger_reports_zero(store):
    summary = codex_usage.usage_summary()
    assert summary["requests"] == 0
    assert summary["output_tokens"] == 0
    assert summary["top_users"] == []


def test_records_and_summarizes_calls(store):
    codex_usage.record_call("U_ALICE", "gpt-5.5", 100)
    codex_usage.record_call("U_ALICE", "gpt-5.5", 50)
    codex_usage.record_call("U_BOB", "gpt-5.4", 25)
    summary = codex_usage.usage_summary()
    assert summary["requests"] == 3
    assert summary["output_tokens"] == 175
    by_user = {u["user_id"]: u["requests"] for u in summary["top_users"]}
    assert by_user == {"U_ALICE": 2, "U_BOB": 1}


def test_excludes_calls_outside_the_window(store):
    from sqlalchemy import text
    codex_usage.record_call("U_OLD", "gpt-5.5", 10)
    with db.get_engine().begin() as c:
        c.execute(text("UPDATE codex_usage SET created = :t"), {"t": time.time() - 7200})
    summary = codex_usage.usage_summary(window_s=3600)  # 1-hour window
    assert summary["requests"] == 0


def test_unknown_user_id_is_grouped_as_unknown(store):
    codex_usage.record_call(None, "gpt-5.5", 10)
    summary = codex_usage.usage_summary()
    assert summary["top_users"] == [{"user_id": "(unknown)", "requests": 1}]


def test_recording_failure_does_not_raise(store, monkeypatch):
    monkeypatch.setattr(codex_usage, "get_engine", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    codex_usage.record_call("U_X", "gpt-5.5", 10)  # must not raise
