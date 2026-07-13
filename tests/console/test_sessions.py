
import pytest

from bott.interfaces.console import sessions


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "test-secret-please-rotate")


def test_round_trip_admin(monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "pulkit.tyagi@axelerant.com")
    tok = sessions.issue_session("pulkit.tyagi@axelerant.com", is_admin=True)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "pulkit.tyagi@axelerant.com", "is_admin": True}


def test_round_trip_member():
    tok = sessions.issue_session("a@axelerant.com", is_admin=False)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "a@axelerant.com", "is_admin": False}


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


def test_claim_ignored_when_no_admin_source_matches():
    """The cookie's `is_admin` claim is advisory only, never trusted on its own: a claim
    of True with no real admin source (env or KV) behind it is not honored."""
    tok = sessions.issue_session("nobody@axelerant.com", is_admin=True)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "nobody@axelerant.com", "is_admin": False}


def test_member_claim_upgraded_live_when_promoted_via_kv(monkeypatch):
    """The reverse of downgrade, and the whole point of recomputing in both directions:
    a member promoted to admin via the console (KV) becomes admin on their very next
    request, without needing to sign out and back in for a fresh cookie claim."""
    from bott.shared import roles
    monkeypatch.setattr(roles, "kv_admins", lambda: {"promoted@axelerant.com"})
    tok = sessions.issue_session("promoted@axelerant.com", is_admin=False)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "promoted@axelerant.com", "is_admin": True}


def test_admin_claim_still_ignored_after_kv_demotion(monkeypatch):
    """A stale cookie claiming is_admin=True for someone who was demoted via KV (and
    isn't env-seeded) is downgraded immediately, same as the BOTT_ADMINS case above."""
    from bott.shared import roles
    monkeypatch.setattr(roles, "env_admins", lambda: set())
    monkeypatch.setattr(roles, "kv_admins", lambda: set())  # demoted: no longer in KV admins
    tok = sessions.issue_session("demoted@axelerant.com", is_admin=True)
    claims = sessions.verify_session(tok)
    assert claims == {"email": "demoted@axelerant.com", "is_admin": False}
