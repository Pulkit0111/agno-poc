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


# ── Slack retry guard ────────────────────────────────────────────────────────────────
# Slack retries after ~3s without an ack; a retry must be acked with 200 and NOT re-run
# the handler (double modal opens, double Home publishes).


def test_app_home_opened_retry_is_acked_without_publishing(tmp_path, monkeypatch):
    published = []
    monkeypatch.setattr("slack_sdk.WebClient.views_publish",
                        lambda self, **kw: published.append(kw))
    body = json.dumps({"event": {"type": "app_home_opened", "user": "U123"}}).encode()
    ts, sig = _sign(body)
    headers = {**_headers(ts, sig), "X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "timeout"}
    r = _client(tmp_path).post("/slack/events", content=body, headers=headers)
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert published == []  # background publish must NOT have been scheduled


def _post_interactivity(client: TestClient, payload: dict, extra_headers: dict | None = None):
    from urllib.parse import urlencode
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ts, sig = _sign(body)
    headers = {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
        "Content-Type": "application/x-www-form-urlencoded",
        **(extra_headers or {}),
    }
    return client.post("/slack/interactivity", content=body, headers=headers)


def test_interactivity_retry_is_acked_without_processing(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("slack_sdk.WebClient.views_open",
                        lambda self, **kw: opened.append(kw))
    payload = {"type": "block_actions", "user": {"id": "U1"}, "trigger_id": "t",
               "actions": [{"action_id": "ask_bott"}]}
    r = _post_interactivity(_client(tmp_path), payload, {"X-Slack-Retry-Num": "1"})
    assert r.status_code == 200
    assert opened == []  # the modal must NOT have been opened again


# ── Approval decisions are ADMIN-ONLY ────────────────────────────────────────────────
# The approval card renders in whatever channel/thread asked for sign-off, so any member
# can click Approve/Dismiss — the handler itself must gate on BOTT_ADMINS.


def _stub_slack_identity(monkeypatch, email: str) -> tuple[list, list]:
    """users_info returns `email`; ephemeral/DM sends are recorded, publishes swallowed."""
    ephemerals, dms = [], []
    monkeypatch.setattr(
        "slack_sdk.WebClient.users_info",
        lambda self, user: {"user": {"profile": {"email": email}, "real_name": "Test User"}})
    monkeypatch.setattr("slack_sdk.WebClient.chat_postEphemeral",
                        lambda self, **kw: ephemerals.append(kw))
    monkeypatch.setattr("slack_sdk.WebClient.chat_postMessage",
                        lambda self, **kw: dms.append(kw))
    monkeypatch.setattr("slack_sdk.WebClient.views_publish", lambda self, **kw: None)
    return ephemerals, dms


def _approval_payload(cmd: str) -> dict:
    return {"type": "block_actions", "user": {"id": "U1"},
            "channel": {"id": "C1"}, "message": {"ts": "111.222"},
            "actions": [{"action_id": cmd, "value": "7"}], "trigger_id": "t"}


def test_non_admin_approve_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")
    ephemerals, _ = _stub_slack_identity(monkeypatch, "member@axelerant.com")
    decided = []
    import bott.shared.approvals as approvals_mod
    monkeypatch.setattr(approvals_mod, "decide",
                        lambda *a, **k: decided.append((a, k)) or True)
    r = _post_interactivity(_client(tmp_path), _approval_payload("approval_approve"))
    assert r.status_code == 200
    assert decided == []  # no state change
    assert ephemerals and "Only admins can decide approvals" in ephemerals[0]["text"]


def test_non_admin_dismiss_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")
    ephemerals, _ = _stub_slack_identity(monkeypatch, "member@axelerant.com")
    decided = []
    import bott.shared.approvals as approvals_mod
    monkeypatch.setattr(approvals_mod, "decide",
                        lambda *a, **k: decided.append((a, k)) or True)
    r = _post_interactivity(_client(tmp_path), _approval_payload("approval_dismiss"))
    assert r.status_code == 200
    assert decided == []
    assert ephemerals and "Only admins can decide approvals" in ephemerals[0]["text"]


def test_admin_approve_works(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")
    ephemerals, _ = _stub_slack_identity(monkeypatch, "admin@axelerant.com")
    decided, built = [], []
    import bott.interfaces.slack_home.router as router_mod
    import bott.shared.approvals as approvals_mod
    import bott.skills.connectors.actions as actions_mod
    monkeypatch.setattr(approvals_mod, "decide",
                        lambda i, approved, decided_by: decided.append((i, approved, decided_by)) or True)
    monkeypatch.setattr(router_mod, "dispatch_approved_build", lambda i: built.append(i))
    monkeypatch.setattr(actions_mod, "dispatch_approved_api", lambda i: None)
    r = _post_interactivity(_client(tmp_path), _approval_payload("approval_approve"))
    assert r.status_code == 200
    assert decided == [(7, True, "U1")]
    assert built == [7]
    assert ephemerals == []  # no refusal for admins


def test_admin_dismiss_works(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")
    _stub_slack_identity(monkeypatch, "admin@axelerant.com")
    decided, built = [], []
    import bott.interfaces.slack_home.router as router_mod
    import bott.shared.approvals as approvals_mod
    monkeypatch.setattr(approvals_mod, "decide",
                        lambda i, approved, decided_by: decided.append((i, approved, decided_by)) or True)
    monkeypatch.setattr(router_mod, "dispatch_approved_build", lambda i: built.append(i))
    r = _post_interactivity(_client(tmp_path), _approval_payload("approval_dismiss"))
    assert r.status_code == 200
    assert decided == [(7, False, "U1")]
    assert built == []  # dismiss never dispatches
