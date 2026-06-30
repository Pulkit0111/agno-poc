# tests/test_codex_tokens.py
import base64
import json
import os
import threading
import time

import pytest
from sqlalchemy import text

from bott.shared import codex_tokens as ct
from bott.shared import db


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
