import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import oidc, sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "shh")
    monkeypatch.setenv("CONSOLE_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(build_console_router())
    return TestClient(app, follow_redirects=False)


def _login_cookie(email="member@axelerant.com", is_admin=False):
    return {sessions.COOKIE_NAME: sessions.issue_session(email, is_admin)}


def test_login_redirects_to_slack(client):
    r = client.get("/api/console/auth/login")
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://slack.com/openid/connect/authorize?")
    assert "oidc_state" in r.cookies


def test_callback_sets_session_and_redirects(client, monkeypatch):
    monkeypatch.setattr(oidc, "exchange_code",
                        lambda code: {"email": "admin@axelerant.com", "name": "A"})
    client.cookies.set("oidc_state", "s1")
    r = client.get("/api/console/auth/callback?code=c&state=s1")
    assert r.status_code == 307
    assert r.headers["location"] == "http://localhost:3000/"
    claims = sessions.verify_session(r.cookies[sessions.COOKIE_NAME])
    assert claims == {"email": "admin@axelerant.com", "is_admin": True}


def test_callback_rejects_bad_state(client, monkeypatch):
    monkeypatch.setattr(oidc, "exchange_code", lambda code: {"email": "a@x.com", "name": "A"})
    client.cookies.set("oidc_state", "s1")
    r = client.get("/api/console/auth/callback?code=c&state=WRONG")
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_state"


def test_callback_failed_exchange_is_401(client, monkeypatch):
    monkeypatch.setattr(oidc, "exchange_code", lambda code: None)
    client.cookies.set("oidc_state", "s1")
    r = client.get("/api/console/auth/callback?code=c&state=s1")
    assert r.status_code == 401


def test_me_requires_session(client):
    r = client.get("/api/console/v1/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "unauthenticated"


def test_me_returns_identity(client):
    client.cookies.update(_login_cookie("member@axelerant.com"))
    assert client.get("/api/console/v1/me").json() == {
        "email": "member@axelerant.com", "is_admin": False}


def test_logout_clears_cookie(client):
    client.cookies.update(_login_cookie())
    r = client.post("/api/console/auth/logout")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    # deletion arrives as a Set-Cookie with empty value
    assert f'{sessions.COOKIE_NAME}=""' in r.headers.get("set-cookie", "")
