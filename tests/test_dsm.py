"""DSM standup: collection storage round-trip + submission rendering (no network)."""

from __future__ import annotations

from bott.shared.persistence import standup
from bott.skills import dsm


def test_round_and_responses_round_trip(tmp_path):
    db = str(tmp_path / "s.db")
    standup.open_round("core", "2026-06-18", "C1", "111.1", db_file=db)
    assert standup.get_round("core", "2026-06-18", db_file=db) == {"channel": "C1", "thread_ts": "111.1"}
    standup.add_response("core", "2026-06-18", "U1", "did x", "do y", "blocked on infra", db_file=db)
    standup.add_response("core", "2026-06-18", "U2", "a", "b", "", db_file=db)
    rs = standup.responses("core", "2026-06-18", db_file=db)
    assert [r["user"] for r in rs] == ["U1", "U2"]
    # A different day is a different round.
    assert standup.responses("core", "2026-06-19", db_file=db) == []


def test_render_submissions_groups_blockers():
    out = dsm._render_submissions("core", [
        {"user": "U1", "yesterday": "x", "today": "y", "blockers": "infra creds"},
        {"user": "U2", "yesterday": "a", "today": "b", "blockers": ""},
    ])
    assert "<@U1>" in out and "<@U2>" in out
    assert "infra creds" in out
    assert "Blockers to discuss" in out


def test_render_submissions_empty():
    assert "No updates" in dsm._render_submissions("core", [])
