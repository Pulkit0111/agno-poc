"""Home-tab schedule rows: real labels + times (guards the cron_expr / '?' regression)."""

from __future__ import annotations

from agno.db.sqlite import SqliteDb

from bott.interfaces.slack_home import service


def _db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "s.db"))


def test_delivery_row_shows_account_name_and_real_time(tmp_path):
    db = _db(tmp_path)
    service.create_delivery(db, "uuid-1", "wrap", "C123", "weekdays", "09:00", band="high")
    rows = service.list_rows(db)
    assert len(rows) == 1
    r = rows[0]
    assert r["label"] == "wrap"          # not the raw UUID
    assert r["channel"] == "C123"
    assert r["icon"] == "🔴"             # band -> icon
    assert r["when"].startswith("Weekdays 9:00 AM")  # not "?"


def test_minutely_delivery_reads_as_every_minute(tmp_path):
    db = _db(tmp_path)
    service.create_delivery(db, "uuid-2", "acme", "C1", "minutely", "09:00")
    row = next(r for r in service.list_rows(db) if r["label"] == "acme")
    assert "Every minute" in row["when"]


def test_dsm_three_phases_merge_into_one_row(tmp_path):
    db = _db(tmp_path)
    # call 10:00, open 2h before (08:00), pre-read 1h before (09:00), summary 10:30.
    service.create_dsm(db, "core", "C9", "10:00", 120, 60, "10:30", "weekdays")
    rows = [r for r in service.list_rows(db) if r["icon"] == "👥"]
    assert len(rows) == 1
    w = rows[0]["when"]
    assert "Open 8:00 AM" in w and "Pre-read 9:00 AM" in w and "Call summary 10:30 AM" in w
    assert len(rows[0]["remove_ids"]) == 3  # removing the row deletes all three


def test_security_digest_row(tmp_path):
    db = _db(tmp_path)
    service.create_security(db, "C5", "daily", "09:00")
    rows = [r for r in service.list_rows(db) if r["icon"] == "🔒"]
    assert len(rows) == 1
    assert rows[0]["channel"] == "C5"
    assert rows[0]["when"].startswith("Daily 9:00 AM")
    assert len(rows[0]["remove_ids"]) == 1


def test_concierge_schedules_excluded_from_home(tmp_path):
    db = _db(tmp_path)
    from bott.skills import scheduling
    scheduling.create_recurring_task(db, user_id="x@axelerant.com", task_name="brief",
                                     instruction="my items", cron="0 8 * * *")
    assert service.list_rows(db) == []


def test_list_raw_flags_concierge_rows_as_personal_and_shows_enabled_state(tmp_path):
    """list_raw() now includes personal (concierge:) rows too — schedules parity means the
    console can manage them like any other, distinguished by the `personal` flag rather
    than being silently dropped."""
    from agno.db.sqlite import SqliteDb

    from bott.interfaces.slack_home import service
    from bott.skills import scheduling

    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    scheduling.create_security_digest(db, channel="#sec", cron="0 9 * * *")
    scheduling.create_recurring_task(
        db, user_id="alice@axelerant.com", task_name="brief",
        instruction="hi", cron="0 8 * * *",
    )
    rows = service.list_raw(db)
    assert len(rows) == 2
    security_row = next(r for r in rows if r["channel"] == "#sec")
    assert security_row["enabled"] is True
    assert security_row["personal"] is False
    concierge_row = next(r for r in rows if r["personal"] is True)
    assert concierge_row["created_by"] == "alice@axelerant.com"


def test_pause_then_resume_round_trip(tmp_path):
    from agno.db.sqlite import SqliteDb

    from bott.interfaces.slack_home import service
    from bott.skills import scheduling

    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = scheduling.create_security_digest(db, channel="#sec", cron="0 9 * * *")
    assert service.pause(db, sch.id) is True
    assert service.list_raw(db)[0]["enabled"] is False
    assert service.resume(db, sch.id) is True
    assert service.list_raw(db)[0]["enabled"] is True


def test_pause_missing_schedule_returns_false(tmp_path):
    from agno.db.sqlite import SqliteDb

    from bott.interfaces.slack_home import service

    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    assert service.pause(db, "does-not-exist") is False
