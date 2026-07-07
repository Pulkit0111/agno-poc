
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


def test_admin_claim_revoked_live_when_removed_from_bott_admins(monkeypatch):
    """Regression: removing someone from BOTT_ADMINS used to have no effect until their
    already-issued (up to 7-day) session token naturally expired. The admin claim baked in
    at login must be re-checked on every verify, not trusted for the token's whole life."""
    tok = sessions.issue_session("former-admin@axelerant.com", is_admin=True)
    # At issue time they were an admin; BOTT_ADMINS has since been updated without them.
    monkeypatch.setenv("BOTT_ADMINS", "current-admin@axelerant.com")
    claims = sessions.verify_session(tok)
    assert claims == {"email": "former-admin@axelerant.com", "is_admin": False}


def test_admin_claim_still_honored_when_still_in_bott_admins(monkeypatch):
    tok = sessions.issue_session("admin@axelerant.com", is_admin=True)
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com,other@axelerant.com")
    claims = sessions.verify_session(tok)
    assert claims == {"email": "admin@axelerant.com", "is_admin": True}


def test_admin_claim_trusted_when_bott_admins_unset():
    """No live authority to check against (BOTT_ADMINS unset/empty) — fall back to
    trusting the token's own claim rather than blanket-revoking every admin session."""
    tok = sessions.issue_session("admin@axelerant.com", is_admin=True)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "admin@axelerant.com", "is_admin": True}


def test_non_admin_claim_never_upgraded(monkeypatch):
    """The live check only ever downgrades — a non-admin token can't become admin just
    because its email happens to appear in BOTT_ADMINS later."""
    tok = sessions.issue_session("member@axelerant.com", is_admin=False)
    monkeypatch.setenv("BOTT_ADMINS", "member@axelerant.com")
    claims = sessions.verify_session(tok)
    assert claims == {"email": "member@axelerant.com", "is_admin": False}
