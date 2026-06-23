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


def test_security_digest_scope_and_metadata(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_security_digest(db, channel="C5", cron="0 9 * * *")
    p = _payload(sch)
    assert p["user_id"] == "feed:drupal-sa"
    assert p["session_id"] == "security:drupal"
    assert "drupal_security_advisories" in p["message"]
    import json
    desc = json.loads(getattr(sch, "description", "{}") or "{}")
    assert desc["kind"] == "security"


def test_sprint_report_scoped_to_engagement(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_sprint_report(db, engagement="padi", cron="0 17 * * 5")
    p = _payload(sch)
    assert p["user_id"] == "engagement:PADI"  # normalized to the project key
    assert p["session_id"] == "sprint-report:PADI"
    assert "build_sprint_dossier" in p["message"] and "publish_sprint_report" in p["message"]
    # No channel pinned -> the run resolves it via Memra.
    assert "Memra" in p["message"]
    assert getattr(sch, "name", "") == "sprint-report:PADI"
    import json
    desc = json.loads(getattr(sch, "description", "{}") or "{}")
    assert desc["kind"] == "sprint"


def test_sprint_report_pinned_channel(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_sprint_report(db, engagement="ACME", cron="0 17 * * 5", channel="#acme")
    msg = _payload(sch)["message"]
    assert "#acme" in msg and "Memra" not in msg


def test_sentiment_report_portfolio_scope_and_prompt(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_sentiment_report(db, channel="#leads", cron="0 9 * * 1")
    p = _payload(sch)
    assert p["user_id"] == "portfolio:delivery-health"
    assert p["session_id"] == "sentiment-report"
    assert "memra_engagements_at_risk" in p["message"]  # portfolio sentiment source
    assert "#leads" in p["message"]
    assert getattr(sch, "name", "") == "sentiment-report:portfolio"
    import json
    assert json.loads(getattr(sch, "description", "{}"))["kind"] == "sentiment"


def test_schedules_have_retries_to_absorb_boot_race(tmp_path):
    """The Agno poller fires overdue (catch-up) schedules during lifespan startup,
    which can race uvicorn and fail with 'All connection attempts failed'. Every
    schedule must carry retries so that transient connect failure self-heals instead
    of being lost on a single attempt."""
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    made = [
        scheduling.create_security_digest(db, channel="C5", cron="0 9 * * *"),
        scheduling.create_recurring_task(
            db, user_id="a@x.com", task_name="t", instruction="x", cron="0 8 * * *"
        ),
        scheduling.create_delivery_synthesis(
            db, engagement_id="eng-1", channel="#e", cron="0 9 * * 1"
        ),
        scheduling.create_dsm_open(db, team_id="core", channel="#c", cron="0 8 * * 1-5"),
        scheduling.create_sprint_report(db, engagement="padi", cron="0 17 * * 5"),
        scheduling.create_sentiment_report(db, channel="#leads", cron="0 9 * * 1"),
    ]
    for sch in made:
        assert getattr(sch, "max_retries", 0) >= 1, f"{sch.name} has no retries"
        assert getattr(sch, "retry_delay_seconds", 0) >= 1, f"{sch.name} has no retry delay"


def test_dsm_three_phases_share_team_session_and_call_tools(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    o = scheduling.create_dsm_open(db, team_id="core", channel="#core", cron="0 8 * * 1-5")
    p = scheduling.create_dsm_preread(db, team_id="core", channel="#core", cron="0 9 * * 1-5")
    c = scheduling.create_dsm_callsummary(db, team_id="core", channel="#core", cron="30 10 * * 1-5")
    assert _payload(o)["session_id"] == _payload(p)["session_id"] == _payload(c)["session_id"] == "dsm:core"
    assert "open_standup" in _payload(o)["message"]
    assert "close_standup" in _payload(p)["message"]
    assert "post_call_summary" in _payload(c)["message"]
