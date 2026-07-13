"""Console /v1/users endpoints: GET (roster incl. invited rows), POST role (promote/
demote), POST invite, DELETE invite. Exercises the Task 10 security invariants at the
HTTP layer: member is 403 everywhere, env admins are locked, invites are domain-checked,
and — the whole point of routing session verification through roles.is_admin live — a
promote takes effect on the very next request without a fresh login."""

import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAIN", "axelerant.com")
    # Fresh, isolated settings table per test — roles.py's KV writes must not leak into
    # the shared default agentos.db (or into other tests in the same run).
    from bott.shared import db as db_mod
    from bott.shared.schema import init_schema
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "agentos.db"))
    db_mod.get_engine(fresh=True)
    init_schema()


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def _as(client, email="m@x.com", admin=False):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))
    if admin:
        import os
        os.environ["BOTT_ADMINS"] = email


# ---------------------------------------------------------------------------
# GET /v1/users — shape, including invited-but-never-signed-in rows
# ---------------------------------------------------------------------------

def test_list_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/users").status_code == 403


def test_list_shapes_env_kv_and_invited_rows(client, monkeypatch):
    monkeypatch.setenv("BOTT_ADMINS", "seeded@axelerant.com")
    from bott.shared.persistence import records
    monkeypatch.setattr(records, "list_known_users", lambda: [
        {"user_id": "seeded@axelerant.com", "last_active": 300.0},
        {"user_id": "promoted@axelerant.com", "last_active": 200.0},
        {"user_id": "member@axelerant.com", "last_active": 100.0},
    ])
    from bott.shared import roles
    roles.set_role("promoted@axelerant.com", "admin", actor="seeded@axelerant.com")
    roles.add_invite("pending@axelerant.com", "member", actor="seeded@axelerant.com")

    _as(client, email="seeded@axelerant.com", admin=True)
    rows = client.get("/api/console/v1/users").json()["users"]

    by_email = {r["email"]: r for r in rows}
    assert by_email["seeded@axelerant.com"] == {
        "email": "seeded@axelerant.com", "role": "admin", "locked": True,
        "invited": False, "last_active": 300.0,
    }
    assert by_email["promoted@axelerant.com"] == {
        "email": "promoted@axelerant.com", "role": "admin", "locked": False,
        "invited": False, "last_active": 200.0,
    }
    assert by_email["member@axelerant.com"] == {
        "email": "member@axelerant.com", "role": "member", "locked": False,
        "invited": False, "last_active": 100.0,
    }
    # Invited but never signed in: no last_active, invited=True, not in list_known_users.
    assert by_email["pending@axelerant.com"] == {
        "email": "pending@axelerant.com", "role": "member", "locked": False,
        "invited": True, "last_active": None,
    }


def test_consumed_invite_does_not_double_appear(client, monkeypatch):
    """Once someone signs in and their invite is consumed, they show up via
    list_known_users only — never as a second 'invited' row."""
    monkeypatch.setenv("BOTT_ADMINS", "seeded@axelerant.com")
    from bott.shared.persistence import records
    monkeypatch.setattr(records, "list_known_users", lambda: [
        {"user_id": "was-invited@axelerant.com", "last_active": 50.0},
    ])
    from bott.shared import roles
    roles.add_invite("was-invited@axelerant.com", "admin", actor="seeded@axelerant.com")
    roles.consume_invite("was-invited@axelerant.com")  # simulates their first sign-in

    _as(client, email="seeded@axelerant.com", admin=True)
    rows = client.get("/api/console/v1/users").json()["users"]
    matches = [r for r in rows if r["email"] == "was-invited@axelerant.com"]
    assert len(matches) == 1
    assert matches[0] == {
        "email": "was-invited@axelerant.com", "role": "admin", "locked": False,
        "invited": False, "last_active": 50.0,
    }


# ---------------------------------------------------------------------------
# POST /v1/users/{email}/role — promote / demote
# ---------------------------------------------------------------------------

def test_set_role_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/users/other@x.com/role", json={"role": "admin"})
    assert r.status_code == 403


def test_promote_member_to_admin(client):
    _as(client, email="admin@x.com", admin=True)
    r = client.post("/api/console/v1/users/member@x.com/role", json={"role": "admin"})
    assert r.status_code == 200
    assert r.json() == {"email": "member@x.com", "role": "admin"}

    from bott.shared import roles
    assert roles.is_admin("member@x.com") is True


def test_promote_takes_effect_on_next_request_without_relogin(client):
    """The core session invariant: a member's ALREADY-ISSUED cookie (is_admin=False,
    from before they were promoted) must reflect admin on their very next request — no
    sign-out/sign-in round trip required."""
    _as(client, email="admin@x.com", admin=True)
    client.post("/api/console/v1/users/soon-admin@x.com/role", json={"role": "admin"})

    # soon-admin's cookie was issued (hypothetically) BEFORE the promotion, so its own
    # is_admin claim is False — but verify_session must recompute live, not trust it.
    client.cookies.set(sessions.COOKIE_NAME,
                        sessions.issue_session("soon-admin@x.com", is_admin=False))
    me = client.get("/api/console/v1/me").json()
    assert me == {"email": "soon-admin@x.com", "is_admin": True}

    # And the promoted user can now hit an admin-only endpoint on that same old cookie.
    assert client.get("/api/console/v1/users").status_code == 200


def test_demote_kv_admin_back_to_member(client):
    _as(client, email="admin@x.com", admin=True)
    from bott.shared import roles
    roles.set_role("kv-admin@x.com", "admin", actor="admin@x.com")
    r = client.post("/api/console/v1/users/kv-admin@x.com/role", json={"role": "member"})
    assert r.status_code == 200
    assert roles.is_admin("kv-admin@x.com") is False


def test_demote_env_admin_is_locked(client):
    _as(client, email="admin@x.com", admin=True)
    r = client.post("/api/console/v1/users/admin@x.com/role", json={"role": "member"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "locked"
    from bott.shared import roles
    assert roles.is_admin("admin@x.com") is True


def test_demote_last_admin_is_conflict(client):
    """A KV-only admin (no BOTT_ADMINS at all) who is the sole admin can't demote
    themselves — that would leave zero admins. Deliberately does NOT go through the
    `_as(..., admin=True)` shim (which stamps BOTT_ADMINS) so this admin is KV-only,
    matching the invariant's real-world scenario."""
    from bott.shared import roles
    roles.set_role("only-admin@x.com", "admin", actor="only-admin@x.com")
    client.cookies.set(sessions.COOKIE_NAME,
                        sessions.issue_session("only-admin@x.com", is_admin=False))
    r = client.post("/api/console/v1/users/only-admin@x.com/role", json={"role": "member"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "last_admin"


def test_set_role_bad_role_is_422(client):
    _as(client, email="admin@x.com", admin=True)
    r = client.post("/api/console/v1/users/m@x.com/role", json={"role": "superadmin"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "bad_role"


# ---------------------------------------------------------------------------
# POST /v1/users/invite, DELETE /v1/users/invite/{email}
# ---------------------------------------------------------------------------

def test_invite_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/users/invite",
                    json={"email": "new@axelerant.com", "role": "member"})
    assert r.status_code == 403


def test_invite_creates_pending_role(client):
    _as(client, email="admin@x.com", admin=True)
    r = client.post("/api/console/v1/users/invite",
                    json={"email": "New@Axelerant.com", "role": "admin"})
    assert r.status_code == 200
    assert r.json() == {"email": "new@axelerant.com", "role": "admin", "invited": True}
    from bott.shared import roles
    assert roles.invites() == {"new@axelerant.com": "admin"}


def test_invite_wrong_domain_is_422(client):
    _as(client, email="admin@x.com", admin=True)
    r = client.post("/api/console/v1/users/invite",
                    json={"email": "outsider@gmail.com", "role": "member"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "wrong_domain"
    from bott.shared import roles
    assert roles.invites() == {}


def test_revoke_invite_requires_admin(client):
    _as(client, admin=False)
    r = client.delete("/api/console/v1/users/invite/new@axelerant.com")
    assert r.status_code == 403


def test_revoke_invite(client):
    _as(client, email="admin@x.com", admin=True)
    client.post("/api/console/v1/users/invite",
               json={"email": "new@axelerant.com", "role": "member"})
    r = client.delete("/api/console/v1/users/invite/new@axelerant.com")
    assert r.status_code == 200
    from bott.shared import roles
    assert roles.invites() == {}


def test_revoke_invite_404_when_absent(client):
    _as(client, email="admin@x.com", admin=True)
    r = client.delete("/api/console/v1/users/invite/nobody@axelerant.com")
    assert r.status_code == 404
