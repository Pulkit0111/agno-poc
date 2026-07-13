"""bott.shared.roles — the single admin/invite source of truth: env ∪ KV admins, invite
lifecycle, and the security invariants from the Task 10 brief:
  1. env-seeded admins can never be demoted via set_role (RoleError "locked")
  2. invites are domain-allowlisted and lowercase-normalized
  3. a demotion that would leave zero admins is blocked (RoleError "last_admin")
  4. consume_invite is idempotent and safe when there's no invite
"""

from __future__ import annotations

import pytest

from bott.shared import db, roles, schema


@pytest.fixture(autouse=True)
def dbenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "roles.db"))
    monkeypatch.delenv("BOTT_ADMINS", raising=False)
    db.get_engine(fresh=True)
    schema.init_schema()
    yield


# ---------------------------------------------------------------------------
# env_admins / kv_admins / is_admin union
# ---------------------------------------------------------------------------

def test_env_admins_reads_bott_admins(monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "a@x.com, B@x.com")
    assert roles.env_admins() == {"a@x.com", "b@x.com"}


def test_kv_admins_empty_by_default():
    assert roles.kv_admins() == set()


def test_kv_admins_reflects_promoted_role():
    roles.set_role("member@x.com", "admin", actor="admin@x.com")
    assert roles.kv_admins() == {"member@x.com"}


def test_is_admin_unions_env_and_kv(monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "env-admin@x.com")
    roles.set_role("kv-admin@x.com", "admin", actor="env-admin@x.com")
    assert roles.is_admin("env-admin@x.com") is True
    assert roles.is_admin("kv-admin@x.com") is True
    assert roles.is_admin("nobody@x.com") is False


def test_is_admin_case_insensitive(monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "Admin@X.com")
    assert roles.is_admin("admin@x.com") is True
    assert roles.is_admin("ADMIN@X.COM") is True


def test_is_admin_blank_email_is_false():
    assert roles.is_admin("") is False
    assert roles.is_admin(None) is False


# ---------------------------------------------------------------------------
# set_role — the security invariants
# ---------------------------------------------------------------------------

def test_promote_member_to_admin_via_kv():
    roles.set_role("m@x.com", "admin", actor="a@x.com")
    assert roles.is_admin("m@x.com") is True


def test_demote_kv_admin_back_to_member():
    roles.set_role("m@x.com", "admin", actor="a@x.com")
    roles.set_role("other@x.com", "admin", actor="a@x.com")  # keep >1 admin so this isn't the last
    roles.set_role("m@x.com", "member", actor="a@x.com")
    assert roles.is_admin("m@x.com") is False


def test_env_admin_can_never_be_demoted(monkeypatch):
    """Invariant 1: demoting an env-seeded admin raises, never silently no-ops."""
    monkeypatch.setenv("BOTT_ADMINS", "seeded@x.com")
    with pytest.raises(roles.RoleError) as exc:
        roles.set_role("seeded@x.com", "member", actor="attacker@x.com")
    assert exc.value.slug == "locked"
    assert roles.is_admin("seeded@x.com") is True  # still admin — the raise wasn't cosmetic


def test_env_admin_demote_raises_even_by_themselves(monkeypatch):
    """An env admin can't even demote themselves — env-seeded is permanent for the
    life of the process, full stop."""
    monkeypatch.setenv("BOTT_ADMINS", "seeded@x.com")
    with pytest.raises(roles.RoleError):
        roles.set_role("seeded@x.com", "member", actor="seeded@x.com")


def test_last_kv_admin_cannot_be_demoted_to_zero():
    """Invariant 5: block a demotion that would leave zero admins (env is empty here, so
    this KV admin is the only one there is)."""
    roles.set_role("only-admin@x.com", "admin", actor="only-admin@x.com")
    with pytest.raises(roles.RoleError) as exc:
        roles.set_role("only-admin@x.com", "member", actor="only-admin@x.com")
    assert exc.value.slug == "last_admin"
    assert roles.is_admin("only-admin@x.com") is True


def test_demoting_one_of_several_admins_is_fine():
    roles.set_role("a1@x.com", "admin", actor="a1@x.com")
    roles.set_role("a2@x.com", "admin", actor="a1@x.com")
    roles.set_role("a1@x.com", "member", actor="a2@x.com")
    assert roles.is_admin("a1@x.com") is False
    assert roles.is_admin("a2@x.com") is True


def test_last_admin_guard_does_not_block_env_backed_admin(monkeypatch):
    """When an env admin exists, demoting the sole KV admin never zeroes out admins —
    the env admin is still there — so this must succeed."""
    monkeypatch.setenv("BOTT_ADMINS", "seeded@x.com")
    roles.set_role("only-kv-admin@x.com", "admin", actor="seeded@x.com")
    roles.set_role("only-kv-admin@x.com", "member", actor="seeded@x.com")
    assert roles.is_admin("only-kv-admin@x.com") is False


def test_demoting_a_non_admin_is_a_harmless_no_op():
    roles.set_role("already-member@x.com", "member", actor="a@x.com")
    assert roles.is_admin("already-member@x.com") is False


def test_set_role_rejects_unknown_role():
    with pytest.raises(roles.RoleError) as exc:
        roles.set_role("x@x.com", "superadmin", actor="a@x.com")
    assert exc.value.slug == "bad_role"


def test_set_role_normalizes_case_and_whitespace():
    roles.set_role(" Person@X.com ", "ADMIN", actor="a@x.com")
    assert roles.is_admin("person@x.com") is True


# ---------------------------------------------------------------------------
# invites — domain allowlist + consume lifecycle
# ---------------------------------------------------------------------------

def test_add_invite_and_list():
    roles.add_invite("new@axelerant.com", "member", actor="a@x.com")
    assert roles.invites() == {"new@axelerant.com": "member"}


def test_add_invite_normalizes_case():
    roles.add_invite("New@Axelerant.com", "admin", actor="a@x.com")
    assert roles.invites() == {"new@axelerant.com": "admin"}


def test_add_invite_rejects_wrong_domain(monkeypatch):
    """Invariant 3: an invite can't plant access for an email OIDC login itself would
    reject at the domain check."""
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAIN", "axelerant.com")
    with pytest.raises(roles.RoleError) as exc:
        roles.add_invite("outsider@gmail.com", "admin", actor="a@x.com")
    assert exc.value.slug == "wrong_domain"
    assert roles.invites() == {}


def test_add_invite_rejects_bad_role():
    with pytest.raises(roles.RoleError) as exc:
        roles.add_invite("new@axelerant.com", "owner", actor="a@x.com")
    assert exc.value.slug == "bad_role"


def test_revoke_invite_removes_it():
    roles.add_invite("new@axelerant.com", "member", actor="a@x.com")
    assert roles.revoke_invite("new@axelerant.com") is True
    assert roles.invites() == {}


def test_revoke_invite_no_op_when_absent():
    assert roles.revoke_invite("nobody@axelerant.com") is False


def test_consume_invite_promotes_and_clears():
    """Invariant 6: consume_invite converts the invite into a real role and the invite
    disappears."""
    roles.add_invite("new@axelerant.com", "admin", actor="a@x.com")
    role = roles.consume_invite("new@axelerant.com")
    assert role == "admin"
    assert roles.is_admin("new@axelerant.com") is True
    assert roles.invites() == {}


def test_consume_invite_member_role():
    roles.add_invite("new@axelerant.com", "member", actor="a@x.com")
    role = roles.consume_invite("new@axelerant.com")
    assert role == "member"
    assert roles.is_admin("new@axelerant.com") is False


def test_consume_invite_is_idempotent_and_safe_with_no_invite():
    """Calling consume_invite for an email with no pending invite is a safe no-op —
    every subsequent sign-in for the same (already-consumed) email must not raise."""
    assert roles.consume_invite("nobody@axelerant.com") is None
    roles.add_invite("new@axelerant.com", "admin", actor="a@x.com")
    assert roles.consume_invite("new@axelerant.com") == "admin"
    # second sign-in — invite already cleared, must be a safe no-op, not a re-promote error
    assert roles.consume_invite("new@axelerant.com") is None
    assert roles.is_admin("new@axelerant.com") is True  # role persists from the first consume
