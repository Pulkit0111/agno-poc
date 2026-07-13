import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bott.interfaces.console.router as router_mod
from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")


@pytest.fixture()
def client(tmp_path):
    from agno.db.sqlite import SqliteDb
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "console-test.db"))
    app.include_router(build_console_router(db))
    return TestClient(app)


def _as(client, email, is_admin=False):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, is_admin))
    if is_admin:
        # is_admin is recomputed live from roles.is_admin (env ∪ KV) on every
        # verify_session call — a real admin source must back the claim.
        import os
        os.environ["BOTT_ADMINS"] = email


JOB = {"id": 3, "kind": "review", "args": "{}", "user_id": "m@x.com",
       "status": "done", "attempts": 1, "error": None, "created": 1.0}


def test_jobs_mine(client, monkeypatch):
    monkeypatch.setattr(router_mod.queue, "recent_jobs_for",
                        lambda uid, limit=25: [{"id": 3, "kind": "review",
                                                "status": "done", "created": 1.0}])
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/jobs").json()["jobs"][0]["kind"] == "review"


def test_jobs_all_requires_admin(client, monkeypatch):
    monkeypatch.setattr(router_mod.queue, "recent_jobs", lambda limit=25: [JOB])
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/jobs?scope=all").status_code == 403
    _as(client, "adm@x.com", is_admin=True)
    assert client.get("/api/console/v1/jobs?scope=all").json()["jobs"] == [JOB]


def test_job_detail_owner_only(client, monkeypatch):
    monkeypatch.setattr(router_mod.queue, "job_detail", lambda i: dict(JOB))
    _as(client, "other@x.com")
    assert client.get("/api/console/v1/jobs/3").status_code == 403
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/jobs/3").json()["id"] == 3


def test_job_detail_missing_404(client, monkeypatch):
    monkeypatch.setattr(router_mod.queue, "job_detail", lambda i: None)
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/jobs/9").status_code == 404


def test_jobs_counts_requires_admin(client, monkeypatch):
    monkeypatch.setattr(router_mod.queue, "job_counts", lambda: {})
    monkeypatch.setattr(router_mod.queue, "count_failed_since", lambda ts: 0)
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/jobs/counts").status_code == 403


def test_jobs_counts_maps_pending_to_queued(client, monkeypatch):
    monkeypatch.setattr(router_mod.queue, "job_counts",
                        lambda: {"pending": 2, "running": 1, "done": 5, "failed": 3})
    monkeypatch.setattr(router_mod.queue, "count_failed_since", lambda ts: 1)
    _as(client, "adm@x.com", is_admin=True)
    assert client.get("/api/console/v1/jobs/counts").json() == {
        "running": 1, "queued": 2, "done": 5, "failed": 3, "failed_24h": 1}
