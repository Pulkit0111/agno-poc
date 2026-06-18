"""The App Home gateway: signature enforcement, challenge echo, app_home_opened ack.

(The chat-forward path and live Home publish need a running server + Slack, so they're
exercised manually, not here.)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.slack_home import build_slack_home_router

SECRET = "test-signing-secret"


def _sign(body: bytes, ts: str | None = None) -> tuple[str, str]:
    ts = ts or str(int(time.time()))
    base = f"v0:{ts}:{body.decode()}".encode()
    sig = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    return ts, sig


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    app.include_router(build_slack_home_router(db, token="xoxb-fake", signing_secret=SECRET))
    return TestClient(app)


def _headers(ts: str, sig: str) -> dict:
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
        "Content-Type": "application/json",
    }


def test_url_verification_echoes_challenge(tmp_path):
    body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
    ts, sig = _sign(body)
    r = _client(tmp_path).post("/slack/events", content=body, headers=_headers(ts, sig))
    assert r.status_code == 200
    assert r.json()["challenge"] == "abc123"


def test_bad_signature_rejected(tmp_path):
    body = b'{"type":"url_verification","challenge":"x"}'
    ts = str(int(time.time()))
    r = _client(tmp_path).post("/slack/events", content=body, headers=_headers(ts, "v0=deadbeef"))
    assert r.status_code == 403


def test_missing_headers_rejected(tmp_path):
    r = _client(tmp_path).post("/slack/events", content=b"{}")
    assert r.status_code == 400


def test_app_home_opened_is_acked(tmp_path, monkeypatch):
    # Stub the network call the background publish would make.
    monkeypatch.setattr("slack_sdk.WebClient.views_publish", lambda self, **kw: None)
    body = json.dumps({"event": {"type": "app_home_opened", "user": "U123"}}).encode()
    ts, sig = _sign(body)
    r = _client(tmp_path).post("/slack/events", content=body, headers=_headers(ts, sig))
    assert r.status_code == 200
    assert r.json().get("ok") is True
