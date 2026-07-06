import time

import pytest

from bott.interfaces.console import sessions


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "test-secret-please-rotate")


def test_round_trip():
    tok = sessions.issue_session("pulkit.tyagi@axelerant.com", is_admin=True)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "pulkit.tyagi@axelerant.com", "is_admin": True}


def test_tampered_token_rejected():
    tok = sessions.issue_session("a@axelerant.com", is_admin=False)
    body, sig = tok.rsplit(".", 1)
    assert sessions.verify_session(body + "." + "0" * len(sig)) is None


def test_expired_token_rejected():
    tok = sessions.issue_session("a@axelerant.com", is_admin=False, ttl=-1)
    assert sessions.verify_session(tok) is None


def test_garbage_rejected():
    assert sessions.verify_session("not-a-token") is None
    assert sessions.verify_session("") is None


def test_secret_change_invalidates(monkeypatch):
    tok = sessions.issue_session("a@axelerant.com", is_admin=False)
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "different")
    assert sessions.verify_session(tok) is None
