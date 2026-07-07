"""DSM standup: collection storage round-trip + submission rendering (no network)."""

from __future__ import annotations

import pytest

from bott.shared import db
from bott.shared.persistence import standup
from bott.skills import dsm


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    yield


def test_round_and_responses_round_trip(engine):
    standup.open_round("core", "2026-06-18", "C1", "111.1")
    assert standup.get_round("core", "2026-06-18") == {"channel": "C1", "thread_ts": "111.1"}
    standup.add_response("core", "2026-06-18", "U1", "did x", "do y", "blocked on infra")
    standup.add_response("core", "2026-06-18", "U2", "a", "b", "")
    rs = standup.responses("core", "2026-06-18")
    assert [r["user"] for r in rs] == ["U1", "U2"]
    # A different day is a different round.
    assert standup.responses("core", "2026-06-19") == []


def test_open_round_upserts_on_conflict(engine):
    """Re-opening the same team+date updates the thread root instead of erroring."""
    standup.open_round("core", "2026-06-18", "C1", "111.1")
    standup.open_round("core", "2026-06-18", "C2", "222.2")
    assert standup.get_round("core", "2026-06-18") == {"channel": "C2", "thread_ts": "222.2"}


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


def test_open_blocks_value_is_string():
    blocks = dsm.standup_open_blocks(None)
    val = blocks[1]["elements"][0]["value"]
    assert isinstance(val, str) and val != ""


def test_open_standup_guards_missing_team(monkeypatch):
    monkeypatch.setattr(dsm, "_client", lambda: object())  # truthy, won't be used
    out = dsm.open_standup("", "C1")
    assert "team" in out.lower()
