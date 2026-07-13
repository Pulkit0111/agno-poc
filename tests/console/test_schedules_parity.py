"""Schedules parity: owner-or-admin console mutations, created_by stamping, plain-language
cadence, DSM create + preview in the console, and personal (concierge) schedules surfaced
in both the console (`list_raw`) and Slack Home (`list_rows`) — see the task-4 brief's test
list (a)-(i), one test per letter below."""

from __future__ import annotations

import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router
from bott.interfaces.slack_home import service as schedule_service
from bott.skills import scheduling


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")


@pytest.fixture()
def client_and_db(tmp_path):
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    app.include_router(build_console_router(db))
    return TestClient(app), db


def _as(client, email="member@x.com"):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, False))


def _as_admin(client, email="admin@x.com"):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, True))


def _create_security(client, channel="#sec"):
    return client.post("/api/console/v1/schedules", json={
        "kind": "security", "channel": channel, "frequency": "daily", "time": "09:00",
    })


# ---- (a) member creates a schedule -> 200, created_by == member email ----------------

def test_a_member_create_stamps_created_by(client_and_db):
    tc, db = client_and_db
    _as(tc, "member@x.com")
    r = _create_security(tc)
    assert r.status_code == 200
    sch_id = r.json()["id"]
    row = next(x for x in schedule_service.list_raw(db) if x["id"] == sch_id)
    assert row["created_by"] == "member@x.com"


# ---- (b) member pauses own schedule -> 200 -------------------------------------------

def test_b_member_pauses_own_schedule(client_and_db):
    tc, _db = client_and_db
    _as(tc, "member@x.com")
    sch_id = _create_security(tc).json()["id"]
    r = tc.post(f"/api/console/v1/schedules/{sch_id}/pause")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


# ---- (c) member pauses admin's schedule -> 403 not_owner -----------------------------

def test_c_member_cannot_pause_others_schedule(client_and_db):
    tc, _db = client_and_db
    _as_admin(tc, "admin@x.com")
    sch_id = _create_security(tc, "#admin-sec").json()["id"]
    _as(tc, "member@x.com")
    r = tc.post(f"/api/console/v1/schedules/{sch_id}/pause")
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "not_owner"


# ---- (d) admin pauses anyone's -> 200 -------------------------------------------------

def test_d_admin_pauses_anyones_schedule(client_and_db):
    tc, _db = client_and_db
    _as(tc, "member@x.com")
    sch_id = _create_security(tc).json()["id"]
    _as_admin(tc, "admin@x.com")
    r = tc.post(f"/api/console/v1/schedules/{sch_id}/pause")
    assert r.status_code == 200


# ---- (e) legacy row without created_by -> member 403 ---------------------------------

def test_e_legacy_row_without_created_by_is_admin_only(client_and_db):
    tc, db = client_and_db
    sch = scheduling.create_security_digest(db, channel="#legacy", cron="0 9 * * *")  # no created_by
    _as(tc, "member@x.com")
    r = tc.post(f"/api/console/v1/schedules/{sch.id}/pause")
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "not_owner"
    # ...but an admin can still act on it.
    _as_admin(tc, "admin@x.com")
    assert tc.post(f"/api/console/v1/schedules/{sch.id}/pause").status_code == 200


# ---- (f) list_raw rows include cadence, not just raw cron ----------------------------

def test_f_list_raw_includes_plain_cadence(client_and_db):
    tc, db = client_and_db
    scheduling.create_security_digest(db, channel="#sec", cron="0 16 * * 5")  # Fridays 4pm
    _as(tc)
    rows = tc.get("/api/console/v1/schedules").json()["schedules"]
    assert len(rows) == 1
    assert "Friday" in rows[0]["cadence"]
    assert "4:00 PM" in rows[0]["cadence"]
    assert rows[0]["cron"] == "0 16 * * 5"  # still present, just no longer the only display


# ---- (g) preview endpoint returns next-run text --------------------------------------

def test_g_preview_endpoint(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules/preview", json={
        "kind": "security", "frequency": "daily", "time": "09:00",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["cadence"].startswith("Daily")
    assert body["next_run"]  # non-empty


def test_g_preview_requires_auth(client_and_db):
    tc, _db = client_and_db
    r = tc.post("/api/console/v1/schedules/preview", json={
        "kind": "security", "frequency": "daily", "time": "09:00",
    })
    assert r.status_code == 401


def test_g_preview_rejects_bad_frequency(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules/preview", json={
        "kind": "security", "frequency": "fortnightly", "time": "09:00",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_frequency"


# ---- (h) console create with kind="dsm" ----------------------------------------------

def test_h_create_dsm_schedule_via_console(client_and_db):
    tc, db = client_and_db
    _as(tc, "member@x.com")
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "dsm", "team": "core", "channel": "#core", "time": "10:00",
    })
    assert r.status_code == 200
    assert "id" in r.json()
    rows = schedule_service.list_raw(db)
    dsm_rows = [row for row in rows if row["kind"] == "dsm"]
    assert len(dsm_rows) == 3  # open + preread + callsummary
    assert all(row["created_by"] == "member@x.com" for row in dsm_rows)
    assert all(row["channel"] == "#core" for row in dsm_rows)


def test_h_create_dsm_missing_team_is_400(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "dsm", "channel": "#core", "time": "10:00",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "missing_field"


# ---- (i) Slack Home list_rows includes viewer's own personal schedules --------------

def test_i_home_list_rows_includes_viewers_personal_schedules(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s2.db"))
    scheduling.create_recurring_task(
        db, user_id="alice@axelerant.com", task_name="daily-brief",
        instruction="Give me my action items for today.", cron="0 8 * * *",
    )
    scheduling.create_recurring_task(
        db, user_id="bob@axelerant.com", task_name="bob-only-task",
        instruction="Bob's private reminder.", cron="0 9 * * *",
    )

    # No viewer -> personal schedules stay invisible (existing/default behavior preserved).
    assert all(not row.get("personal") for row in schedule_service.list_rows(db))

    rows = schedule_service.list_rows(db, viewer_email="alice@axelerant.com")
    personal = [row for row in rows if row.get("personal")]
    assert len(personal) == 1
    assert "daily-brief" in personal[0]["label"]
    assert personal[0]["run_buttons"] and personal[0]["remove_ids"]
    # Bob's personal task must never leak into Alice's view.
    assert all("bob" not in row["label"].lower() for row in rows)


# ---- create is open to any authenticated user (drops require_admin) -----------------

def test_create_no_longer_requires_admin(client_and_db):
    tc, _db = client_and_db
    _as(tc, "member@x.com")
    assert _create_security(tc).status_code == 200
