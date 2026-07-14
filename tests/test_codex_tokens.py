# tests/test_codex_tokens.py
import base64
import json
import os
import threading
import time

import httpx
import pytest
from sqlalchemy import text

from bott.shared import alerts, db
from bott.shared import codex_tokens as ct


def _jwt(exp: int) -> str:
    # minimal unsigned JWT with an exp claim (only the payload is read)
    head = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"{head}.{payload}.x"


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "ct.db"))
    monkeypatch.setenv("BOTT_SECRET_KEY", __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    # process-local state must not leak between tests
    monkeypatch.setattr(ct, "_cached", None)
    monkeypatch.setattr(ct, "_was_connected", False)
    yield


def test_not_connected_raises(store):
    assert ct.is_connected() is False
    with pytest.raises(ct.CodexNotConnected):
        ct.get_valid_token()


def test_store_and_get_fresh_token(store):
    ct.store_bundle({"access_token": _jwt(int(time.time()) + 3600),
                     "refresh_token": "rt-1", "account_id": "acc-1"})
    assert ct.is_connected() is True
    tok = ct.get_valid_token()
    assert tok.access_token and tok.account_id == "acc-1"


def test_store_rejects_bad_shape(store):
    with pytest.raises(ValueError):
        ct.store_bundle({"access_token": "x"})  # missing refresh_token/account_id


def test_refresh_ahead_when_expired(store, monkeypatch):
    # an already-expired access token → get_valid_token must refresh
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-old", "account_id": "acc-1"})
    calls = []
    def fake_refresh(rt):
        calls.append(rt)
        return {"access_token": _jwt(int(time.time()) + 3600),
                "refresh_token": "rt-new", "account_id": "acc-1"}
    monkeypatch.setattr(ct, "_http_refresh", fake_refresh)
    tok = ct.get_valid_token()
    assert calls == ["rt-old"]          # refreshed once, with the old token
    assert tok.account_id == "acc-1"
    # the rotated refresh_token is persisted
    assert ct._load_bundle()["refresh_token"] == "rt-new"


def test_get_valid_token_carries_refresh_token(store):
    ct.store_bundle({"access_token": _jwt(int(time.time()) + 3600),
                     "refresh_token": "rt-carry", "account_id": "acc-1"})
    tok = ct.get_valid_token()
    assert tok.refresh_token == "rt-carry"


def test_refresh_ahead_result_carries_new_refresh_token(store, monkeypatch):
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-old", "account_id": "acc-1"})
    def fake_refresh(rt):
        return {"access_token": _jwt(int(time.time()) + 3600),
                "refresh_token": "rt-new", "account_id": "acc-1"}
    monkeypatch.setattr(ct, "_http_refresh", fake_refresh)
    tok = ct.get_valid_token()
    assert tok.refresh_token == "rt-new"


def test_bootstrap_from_local_seeds_org_token(store, tmp_path, monkeypatch):
    import base64
    import json
    import time
    af = tmp_path / "auth.json"
    exp = int(time.time()) + 3600
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    access = f"h.{payload}.x"
    af.write_text(json.dumps({"tokens": {"access_token": access, "refresh_token": "r", "account_id": "acc"}}))
    assert ct.is_connected() is False
    assert ct.bootstrap_from_local(str(af)) is True
    assert ct.is_connected() is True
    assert ct.get_valid_token().account_id == "acc"


def test_not_connected_error_is_actionable(store):
    """The chat-path failure on a never-connected org must tell a human what to DO."""
    with pytest.raises(ct.CodexNotConnected) as ei:
        ct.get_valid_token()
    msg = str(ei.value)
    assert "isn't connected to ChatGPT" in msg and "console (Models page)" in msg
    # 401 so codex_model._provider_error marks it non-retryable (retrying can't reconnect)
    assert ct.CodexNotConnected.status_code == 401


def test_steady_state_token_is_served_from_cache(store, monkeypatch):
    """The per-message hot path must do ZERO DB reads once the token is resolved."""
    ct.store_bundle({"access_token": _jwt(int(time.time()) + 3600),
                     "refresh_token": "rt-1", "account_id": "acc-1"})
    first = ct.get_valid_token()
    reads = []
    orig = ct._load_bundle
    monkeypatch.setattr(ct, "_load_bundle", lambda: reads.append(1) or orig())
    second = ct.get_valid_token()
    assert second.access_token == first.access_token
    assert reads == []          # cache hit — the DB was never touched


def test_cache_invalidated_on_store_and_disconnect(store):
    ct.store_bundle({"access_token": _jwt(int(time.time()) + 3600),
                     "refresh_token": "rt-1", "account_id": "acc-1"})
    assert ct.get_valid_token().account_id == "acc-1"   # populates the cache
    ct.store_bundle({"access_token": _jwt(int(time.time()) + 3600),
                     "refresh_token": "rt-2", "account_id": "acc-2"})
    assert ct.get_valid_token().account_id == "acc-2"   # NOT the cached acc-1
    ct.disconnect()
    with pytest.raises(ct.CodexNotConnected):
        ct.get_valid_token()                            # NOT the cached acc-2


def test_new_bundle_survives_failure_after_http_exchange(store, monkeypatch):
    """Durability invariant: the refresh token is SINGLE-USE — once _http_refresh has
    succeeded, a later failure/rollback of the refresh transaction must NOT resurrect the
    old (now provider-invalidated) refresh token, or the org is permanently disconnected.
    CodexToken is constructed AFTER the durable save, so patching it to explode simulates
    the advisory-lock transaction failing right after the HTTP exchange."""
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-old", "account_id": "acc-1"})
    monkeypatch.setattr(ct, "_http_refresh", lambda rt: {
        "access_token": _jwt(int(time.time()) + 3600),
        "refresh_token": "rt-new", "account_id": "acc-1"})

    class Boom(RuntimeError):
        pass

    def exploding(*a, **k):
        raise Boom("simulated failure after the HTTP exchange")

    monkeypatch.setattr(ct, "CodexToken", exploding)
    with pytest.raises(Boom):
        ct.get_valid_token()
    # the rotated bundle was still committed — rt-old must NOT have been resurrected
    assert ct._load_bundle()["refresh_token"] == "rt-new"


def test_refresh_4xx_alerts_admins_and_says_how_to_fix(store, monkeypatch):
    """A 4xx from the provider means the login is DEAD (not flaky): admins get a DM and
    the raised error carries the actionable reconnect message."""
    sent = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: sent.append(text))
    alerts._last_sent.clear()
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-dead", "account_id": "acc-1"})

    def rejected(rt):
        req = httpx.Request("POST", "https://auth.example/token")
        raise httpx.HTTPStatusError("bad", request=req,
                                    response=httpx.Response(400, request=req))

    monkeypatch.setattr(ct, "_http_refresh", rejected)
    with pytest.raises(ct.CodexNotConnected) as ei:
        ct.get_valid_token()
    assert "console (Models page)" in str(ei.value)
    assert sent and "console (Models page)" in sent[0]


def test_refresh_transient_error_does_not_alert_disconnected(store, monkeypatch):
    """A network blip / provider 5xx is NOT a disconnection — no admin DM."""
    sent = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: sent.append(text))
    alerts._last_sent.clear()
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-1", "account_id": "acc-1"})

    def flaky(rt):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ct, "_http_refresh", flaky)
    with pytest.raises(ct.CodexNotConnected):
        ct.get_valid_token()
    assert sent == []


def test_bundle_vanishing_after_being_connected_alerts_admins(store, monkeypatch):
    """Transition-to-disconnected: the token bundle existed and is now gone — admins must
    hear about it (throttled), because every model call is now failing."""
    sent = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: sent.append(text))
    alerts._last_sent.clear()
    ct.store_bundle({"access_token": _jwt(int(time.time()) + 3600),
                     "refresh_token": "rt-1", "account_id": "acc-1"})
    assert ct.get_valid_token().account_id == "acc-1"   # marks "was connected"
    # the row vanishes outside the normal disconnect() path (lost DB, manual delete...)
    with db.get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE provider='codex'"))
    ct._cache_clear()
    with pytest.raises(ct.CodexNotConnected) as ei:
        ct.get_valid_token()
    assert "console (Models page)" in str(ei.value)
    assert sent and "disconnected" in sent[0]


def test_never_connected_does_not_alert(store, monkeypatch):
    """A fresh install with no bundle is not an incident — no admin DM."""
    sent = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: sent.append(text))
    alerts._last_sent.clear()
    with pytest.raises(ct.CodexNotConnected):
        ct.get_valid_token()
    assert sent == []


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs Postgres")
def test_new_bundle_survives_lock_txn_failure_postgres(monkeypatch):
    """Same durability invariant as the SQLite test, but with the REAL advisory-lock
    transaction in play: the rollback of the pg_advisory_xact_lock transaction must not
    take the already-committed rotated bundle down with it."""
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("BOTT_SECRET_KEY",
                       __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    monkeypatch.setattr(ct, "_cached", None)
    monkeypatch.setattr(ct, "_was_connected", False)
    with db.get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE provider='codex'"))
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-old", "account_id": "acc-1"})
    monkeypatch.setattr(ct, "_http_refresh", lambda rt: {
        "access_token": _jwt(int(time.time()) + 3600),
        "refresh_token": "rt-new", "account_id": "acc-1"})

    class Boom(RuntimeError):
        pass

    def exploding(*a, **k):
        raise Boom("simulated failure after the HTTP exchange")

    monkeypatch.setattr(ct, "CodexToken", exploding)
    with pytest.raises(Boom):
        ct.get_valid_token()
    assert ct._load_bundle()["refresh_token"] == "rt-new"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs Postgres")
def test_concurrent_refresh_is_single_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("BOTT_SECRET_KEY",
                       __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    with db.get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE provider='codex'"))
    ct.store_bundle({"access_token": _jwt(int(time.time()) - 10),
                     "refresh_token": "rt-old", "account_id": "acc-1"})
    calls = []
    def fake_refresh(rt):
        calls.append(rt)
        time.sleep(0.3)
        return {"access_token": _jwt(int(time.time()) + 3600),
                "refresh_token": "rt-new", "account_id": "acc-1"}
    monkeypatch.setattr(ct, "_http_refresh", fake_refresh)
    out = []
    def go():
        out.append(ct.get_valid_token().access_token)
    ts = [threading.Thread(target=go) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1          # exactly ONE network refresh across 3 concurrent callers
    assert len(out) == 3            # all three got a token
    assert ct._load_bundle()["refresh_token"] == "rt-new"
