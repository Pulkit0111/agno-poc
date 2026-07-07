"""Origin-check CSRF guard on the console router — the session cookie is SameSite=Lax,
which still allows cross-site top-level POST navigations, so mutating routes verify the
browser-supplied Origin (or Referer) against CONSOLE_BASE_URL's origin."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router

BASE = "https://console.example.com"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")
    monkeypatch.setenv("CONSOLE_BASE_URL", BASE)


@pytest.fixture()
def client(tmp_path):
    from agno.db.sqlite import SqliteDb
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "csrf-test.db"))
    app.include_router(build_console_router(db))
    return TestClient(app)


def _as_admin(client):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session("adm@x.com", True))


def _post(client, headers=None):
    # A cheap mutating route: logout needs no body, no db, no admin.
    return client.post("/api/console/auth/logout", headers=headers or {},
                       follow_redirects=False)


def test_mismatched_origin_rejected(client):
    _as_admin(client)
    r = _post(client, {"Origin": "https://evil.example.net"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "bad_origin"


def test_matching_origin_allowed(client):
    _as_admin(client)
    assert _post(client, {"Origin": BASE}).status_code == 303


def test_no_origin_no_referer_allowed(client):
    # Non-browser clients (curl, scripts) with a valid session cookie carry neither header.
    _as_admin(client)
    assert _post(client).status_code == 303


def test_referer_fallback_mismatch_rejected(client):
    _as_admin(client)
    r = _post(client, {"Referer": "https://evil.example.net/console/approvals"})
    assert r.status_code == 403


def test_referer_fallback_match_allowed(client):
    _as_admin(client)
    assert _post(client, {"Referer": f"{BASE}/approvals"}).status_code == 303


def test_default_port_normalization(client):
    # https origin without an explicit :443 must match a CONSOLE_BASE_URL without one.
    _as_admin(client)
    assert _post(client, {"Origin": "https://console.example.com:443"}).status_code == 303


def test_get_routes_skip_the_guard(client):
    # Reads are CSRF-immune (no state change) — a cross-origin GET must not 403.
    _as_admin(client)
    r = client.get("/api/console/v1/me", headers={"Origin": "https://evil.example.net"})
    assert r.status_code == 200


def test_mutating_route_with_body_also_guarded(client, monkeypatch):
    # The guard is a router-level dependency — spot-check a JSON POST route too.
    _as_admin(client)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True},
                    headers={"Origin": "https://evil.example.net"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "bad_origin"
