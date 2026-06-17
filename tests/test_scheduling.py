"""Scheduled flows persist with user_id/session_id in the payload (isolation for
scheduled runs — the make-or-break requirement)."""

from __future__ import annotations

from agno.db.sqlite import SqliteDb

from bott.skills import scheduling


def _payload(sch) -> dict:
    p = getattr(sch, "payload", None)
    if p is None and isinstance(sch, dict):
        p = sch.get("payload")
    return p or {}


def test_recurring_task_carries_user_id(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_recurring_task(
        db, user_id="alice@axelerant.com", task_name="morning-brief",
        instruction="Give me my action items for today.", cron="0 8 * * *",
    )
    p = _payload(sch)
    assert p["user_id"] == "alice@axelerant.com"
    assert p["session_id"] == "concierge:alice@axelerant.com"
    assert getattr(sch, "endpoint", None) == "/agents/bott/runs"


def test_delivery_synthesis_scoped_to_engagement(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_delivery_synthesis(
        db, engagement_id="eng-123", channel="#eng-123", cron="0 9 * * 1",
    )
    p = _payload(sch)
    assert p["user_id"] == "engagement:eng-123"
    assert "eng-123" in p["message"]


def test_dsm_precall_and_postcall_share_team_session(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    pre = scheduling.create_dsm_precall(db, team_id="core", channel="#core", cron="55 9 * * 1-5")
    post = scheduling.create_dsm_postcall(db, team_id="core", channel="#core", cron="30 10 * * 1-5")
    assert _payload(pre)["session_id"] == _payload(post)["session_id"] == "dsm:core"
