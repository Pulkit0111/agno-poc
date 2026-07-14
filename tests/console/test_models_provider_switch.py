"""Per-role provider overrides + provider catalogs (Task 3, Part A).

`_active()` now surfaces `providers_by_role` (chat/build/review, each via
`resolve_provider`); the admin GET branch also surfaces `catalogs` (per-provider model-id
lists); `apply_model_override` accepts `model.provider.<role>` keys, validated against
{codex, openrouter, bedrock}. See src/bott/interfaces/slack_home/models.py."""
import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def _as(client, email="m@x.com", admin=False):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))
    if admin:
        # is_admin is recomputed live from roles.is_admin (env ∪ KV) on every
        # verify_session call — a real admin source must back the claim.
        import os
        os.environ["BOTT_ADMINS"] = email


def test_admin_get_includes_providers_by_role_and_catalogs(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_fetch_openrouter_models", lambda: ["openai/gpt-5.5", "anthropic/claude-opus-4.8"])
    from bott.shared import config
    monkeypatch.setattr(config, "openrouter_api_key", lambda: "sk-test")
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()

    assert body["active"]["providers_by_role"]["chat"] in ("codex", "openrouter", "bedrock")
    assert body["active"]["providers_by_role"]["build"] in ("codex", "openrouter", "bedrock")
    assert body["active"]["providers_by_role"]["review"] in ("codex", "openrouter", "bedrock")
    assert "openai/gpt-5.5" in body["catalogs"]["openrouter"]
    assert isinstance(body["catalogs"]["codex"], list) and body["catalogs"]["codex"]


def test_admin_post_provider_role_override_then_get_reflects_it(client):
    _as(client, admin=True)
    r = client.post("/api/console/v1/models",
                     json={"key": "model.provider.chat", "value": "openrouter"})
    assert r.status_code == 200, r.text

    body = client.get("/api/console/v1/models").json()
    assert body["active"]["providers_by_role"]["chat"] == "openrouter"


def test_admin_post_invalid_provider_value_is_rejected(client):
    _as(client, admin=True)
    r = client.post("/api/console/v1/models",
                     json={"key": "model.provider.chat", "value": "bogus"})
    assert r.status_code in (400, 422)


def test_member_get_has_no_catalogs_key(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
        "providers_by_role": {"chat": "codex", "build": "codex", "review": "codex"},
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    _as(client, admin=False)
    body = client.get("/api/console/v1/models").json()
    assert "catalogs" not in body


def test_member_post_override_forbidden(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/models",
                     json={"key": "model.provider.chat", "value": "openrouter"})
    assert r.status_code == 403
