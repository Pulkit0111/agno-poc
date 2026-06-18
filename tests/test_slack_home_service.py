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


def test_dsm_pre_and_post_merge_into_one_row(tmp_path):
    db = _db(tmp_path)
    service.create_dsm(db, "core", "C9", "09:55", "10:30", "weekdays")
    rows = [r for r in service.list_rows(db) if r["icon"] == "👥"]
    assert len(rows) == 1
    assert "Pre 9:55 AM" in rows[0]["when"]
    assert "Post 10:30 AM" in rows[0]["when"]
    assert len(rows[0]["remove_ids"]) == 2  # removing the row deletes both


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
