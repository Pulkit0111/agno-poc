# tests/console/test_connectors_add.py
"""POST /connectors/add + DELETE /connectors/{name} — validation, probe-before-store,
codex isolation, and secret-never-echoed-back checks.

Every network/JWT round-trip is monkeypatched at the probes.py candidate-probe layer —
these tests never touch a real network."""

from __future__ import annotations

import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router
from bott.shared import connector_credentials, db


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")
    monkeypatch.setenv("BOTT_ADMINS", "admin@x.com")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "cc.db"))
    monkeypatch.setenv("BOTT_SECRET_KEY", __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def _as(client, email=None, admin=True):
    # is_admin is recomputed LIVE from roles.is_admin (env ∪ KV) on every verify — the
    # claim in the token is advisory only (see sessions.verify_session). So a caller
    # asking for admin=False must NOT default to the env-seeded admin email
    # ('admin@x.com', BOTT_ADMINS above) or they'd be real-admin regardless of this flag.
    if email is None:
        email = "admin@x.com" if admin else "m@x.com"
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))


def _ok_probe(monkeypatch, message="ok"):
    from bott.skills.connectors import probes
    monkeypatch.setattr(probes, "probe_candidate", lambda kind, fields: {"ok": True, "message": message})


def _failing_probe(monkeypatch, message="nope"):
    from bott.skills.connectors import probes
    monkeypatch.setattr(probes, "probe_candidate", lambda kind, fields: {"ok": False, "message": message})


# ── Auth gates ─────────────────────────────────────────────────────────────────────────

def test_add_requires_auth(client):
    r = client.post("/api/console/v1/connectors/add", json={"type": "http_api", "fields": {}})
    assert r.status_code == 401


def test_add_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/connectors/add", json={"type": "http_api", "fields": {}})
    assert r.status_code == 403


def test_remove_requires_auth(client):
    assert client.delete("/api/console/v1/connectors/http-foo").status_code == 401


def test_remove_requires_admin(client):
    _as(client, admin=False)
    assert client.delete("/api/console/v1/connectors/http-foo").status_code == 403


# ── Validation (422s, per type) ─────────────────────────────────────────────────────────

def test_unknown_type_is_422(client):
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={"type": "bogus", "fields": {}})
    assert r.status_code == 422
    assert "Unknown connector type" in r.json()["detail"]["error"]["message"]


@pytest.mark.parametrize("fields,missing", [
    ({}, "App ID"),
    ({"app_id": "1"}, "Private key"),
])
def test_github_app_missing_fields_422(client, fields, missing):
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={"type": "github_app", "fields": fields})
    assert r.status_code == 422
    assert missing in r.json()["detail"]["error"]["message"]


@pytest.mark.parametrize("fields,missing", [
    ({}, "Org slug"),
    ({"org": "acme"}, "Auth token"),
])
def test_sentry_org_missing_fields_422(client, fields, missing):
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={"type": "sentry_org", "fields": fields})
    assert r.status_code == 422
    assert missing in r.json()["detail"]["error"]["message"]


@pytest.mark.parametrize("fields,missing", [
    ({}, "Name/slug"),
    ({"name": "acme"}, "Base URL"),
    ({"name": "acme", "base_url": "not-a-url"}, "Base URL"),
])
def test_http_api_missing_or_bad_fields_422(client, fields, missing):
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={"type": "http_api", "fields": fields})
    assert r.status_code == 422
    assert missing in r.json()["detail"]["error"]["message"]


def test_validation_failure_never_probes_or_stores(client, monkeypatch):
    from bott.skills.connectors import probes

    calls = []
    monkeypatch.setattr(probes, "probe_candidate", lambda kind, fields: calls.append(1) or {"ok": True, "message": "x"})
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={"type": "github_app", "fields": {}})
    assert r.status_code == 422
    assert calls == []
    assert connector_credentials.configured_names() == []


# ── Probe-before-store gate ──────────────────────────────────────────────────────────────

def test_probe_fail_is_422_and_stores_nothing(client, monkeypatch):
    _failing_probe(monkeypatch, "401 unauthorized")
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={
        "type": "http_api", "fields": {"name": "acme", "base_url": "https://acme.example.com"},
    })
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["message"] == "401 unauthorized"
    assert connector_credentials.configured_names() == []


def test_probe_success_stores_and_returns_name(client, monkeypatch):
    _ok_probe(monkeypatch)
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={
        "type": "http_api", "fields": {"name": "Acme API", "base_url": "https://acme.example.com"},
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "name": "http-acme-api"}
    assert connector_credentials.configured_names() == ["http-acme-api"]


def test_add_github_app_stores_under_fixed_name(client, monkeypatch):
    _ok_probe(monkeypatch)
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={
        "type": "github_app", "fields": {"app_id": "1", "private_key": "PEM", "installation_id": "9"},
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "name": "github-app"}
    assert connector_credentials.load("github-app") == {
        "app_id": "1", "installation_id": "9", "private_key": "PEM",
    }


def test_add_sentry_org_stores_under_derived_name(client, monkeypatch):
    _ok_probe(monkeypatch)
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={
        "type": "sentry_org", "fields": {"org": "SecondOrg", "auth_token": "tok"},
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "name": "sentry-secondorg"}


def test_add_passes_candidate_fields_to_probe_not_env(client, monkeypatch):
    """The probe must run against the CANDIDATE fields from the request, not whatever
    (if anything) is already configured via env/store — a bad candidate must fail even if
    the org already has a working default connector of another kind."""
    from bott.skills.connectors import probes

    seen = {}

    def fake(kind, fields):
        seen["kind"] = kind
        seen["fields"] = fields
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(probes, "probe_candidate", fake)
    _as(client)
    client.post("/api/console/v1/connectors/add", json={
        "type": "sentry_org", "fields": {"org": "acme", "auth_token": "tok", "base_url": "https://s.acme.com"},
    })
    assert seen["kind"] == "sentry_org"
    assert seen["fields"] == {"org": "acme", "auth_token": "tok", "base_url": "https://s.acme.com"}


# ── Appears in GET /connectors + probe(name) works after storing ────────────────────────

def test_added_connector_appears_in_list_without_secrets(client, monkeypatch):
    _ok_probe(monkeypatch)
    _as(client)
    client.post("/api/console/v1/connectors/add", json={
        "type": "sentry_org", "fields": {"org": "acme", "auth_token": "super-secret-token"},
    })
    r = client.get("/api/console/v1/connectors")
    assert r.status_code == 200
    added = [c for c in r.json()["connectors"] if c["name"] == "sentry-acme"]
    assert added == [{"name": "sentry-acme", "ok": True, "on": "Added from the console", "off": "", "fix": []}]
    # The secret must never appear ANYWHERE in the list response.
    assert "super-secret-token" not in r.text


def test_stored_connector_is_testable_via_test_endpoint(client, monkeypatch):
    from bott.shared import connector_credentials as cc

    _as(client)
    cc.store("http-acme", {"base_url": "https://acme.example.com"})
    from bott.skills.connectors import probes
    monkeypatch.setattr(probes, "probe_candidate", lambda kind, fields: {"ok": True, "message": f"reached {fields['base_url']}"})
    r = client.post("/api/console/v1/connectors/http-acme/test")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "reached https://acme.example.com"}


def test_metadata_range_base_url_is_422_and_stores_nothing(client, monkeypatch):
    """SSRF tripwire: the link-local/metadata range is refused BEFORE any network
    round-trip (guard in probes._reject_metadata_host), and nothing lands in the store."""
    import httpx

    def get_must_not_be_called(url, headers=None, timeout=None):
        raise AssertionError("no network GET may happen for a refused host")

    monkeypatch.setattr(httpx, "get", get_must_not_be_called)
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={
        "type": "http_api", "fields": {"name": "meta", "base_url": "http://169.254.169.254/latest/"},
    })
    assert r.status_code == 422
    assert "aren't allowed" in r.json()["detail"]["error"]["message"]
    assert connector_credentials.configured_names() == []


def test_added_github_app_does_not_duplicate_the_static_github_card(client, monkeypatch):
    """A console-added GitHub App flips the STATIC 'GitHub' card to Connected (the config
    overlay) — the store-backed 'github-app' entry must NOT also be appended as a second
    card. Exactly one GitHub card in the list; DELETE still works via the store name."""
    _ok_probe(monkeypatch)
    _as(client)
    r = client.post("/api/console/v1/connectors/add", json={
        "type": "github_app", "fields": {"app_id": "1", "private_key": "PEM"},
    })
    assert r.status_code == 200
    cards = client.get("/api/console/v1/connectors").json()["connectors"]
    github_cards = [c for c in cards if c["name"].lower() in ("github", "github-app")]
    assert len(github_cards) == 1
    assert github_cards[0]["name"] == "GitHub"
    assert github_cards[0]["ok"] is True  # the overlay flipped the static card
    # Removal still works through the store name even though no store card is shown.
    assert client.delete("/api/console/v1/connectors/github-app").status_code == 200
    assert connector_credentials.configured_names() == []


# ── DELETE ────────────────────────────────────────────────────────────────────────────

def test_delete_store_backed_connector_ok(client, monkeypatch):
    _ok_probe(monkeypatch)
    _as(client)
    client.post("/api/console/v1/connectors/add", json={
        "type": "http_api", "fields": {"name": "acme", "base_url": "https://acme.example.com"},
    })
    r = client.delete("/api/console/v1/connectors/http-acme")
    assert r.status_code == 200
    assert connector_credentials.configured_names() == []


def test_delete_unknown_name_404s(client):
    _as(client)
    r = client.delete("/api/console/v1/connectors/not-a-thing")
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "unknown_connector"


def test_delete_cannot_remove_codex(client):
    """codex-org lives under a DIFFERENT sentinel user_id — this endpoint must never be
    able to touch it, and 'codex-org'/'codex' were never a store-backed name to begin
    with, so this 404s exactly like any other unknown name."""
    from bott.shared import codex_tokens as ct

    ct.store_bundle({"access_token": "a.b.c", "refresh_token": "rt", "account_id": "acc"})
    _as(client)
    for name in ("codex-org", "codex"):
        r = client.delete(f"/api/console/v1/connectors/{name}")
        assert r.status_code == 404
    assert ct.is_connected() is True  # untouched


def test_delete_member_403s_even_for_a_real_stored_connector(client, monkeypatch):
    _ok_probe(monkeypatch)
    _as(client)
    client.post("/api/console/v1/connectors/add", json={
        "type": "http_api", "fields": {"name": "acme", "base_url": "https://acme.example.com"},
    })
    _as(client, email="m@x.com", admin=False)
    r = client.delete("/api/console/v1/connectors/http-acme")
    assert r.status_code == 403
    assert connector_credentials.configured_names() == ["http-acme"]
