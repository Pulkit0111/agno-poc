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


def _patch_health(monkeypatch, *, last_received="1234.5"):
    import bott.interfaces.slack_home.connectors_panel as connectors_panel
    import bott.interfaces.slack_home.models as models_mod
    import bott.shared.codex_cli as codex_cli
    import bott.shared.persistence.records as records
    monkeypatch.setattr(router_mod.queue, "job_counts",
                        lambda: {"pending": 2, "running": 1, "done": 4, "failed": 3})
    monkeypatch.setattr(router_mod.queue, "count_failed_since", lambda ts: 1)
    monkeypatch.setattr(codex_cli, "is_logged_in", lambda *a, **k: True)
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5", "review": "gpt-5.4"})
    monkeypatch.setattr(connectors_panel, "connector_statuses",
                        lambda: [{"name": "Slack", "ok": True, "on": "connected", "off": ""}])
    monkeypatch.setattr(records, "get_setting", lambda k, default=None: last_received)


def test_health_requires_admin(client, monkeypatch):
    _patch_health(monkeypatch)
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/health").status_code == 403


def test_health_admin_aggregate(client, monkeypatch):
    _patch_health(monkeypatch)
    _as(client, "adm@x.com", is_admin=True)
    body = client.get("/api/console/v1/health").json()
    assert body["model"] == {"connected": True, "provider": "codex"}
    assert body["jobs"] == {"running": 1, "queued": 2, "failed_24h": 1}
    assert body["connectors"] == [{"name": "Slack", "ok": True, "on": "connected", "off": ""}]
    assert body["webhook"] == {"last_received_at": 1234.5}


def test_health_webhook_null_when_never_received(client, monkeypatch):
    _patch_health(monkeypatch, last_received=None)
    _as(client, "adm@x.com", is_admin=True)
    body = client.get("/api/console/v1/health").json()
    assert body["webhook"] == {"last_received_at": None}


def test_reviews_requires_admin(client, monkeypatch):
    import bott.shared.persistence.records as records
    monkeypatch.setattr(records, "recent_reviews", lambda limit=50: [])
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/reviews").status_code == 403


def test_reviews_admin_returns_rows(client, monkeypatch):
    import bott.shared.persistence.records as records
    rows = [{"pr": "acme/web#12", "verdict": "approve",
             "url": "https://github.com/acme/web/pull/12", "created": 1.0}]
    monkeypatch.setattr(records, "recent_reviews", lambda limit=50: rows)
    _as(client, "adm@x.com", is_admin=True)
    assert client.get("/api/console/v1/reviews").json() == {"reviews": rows}
