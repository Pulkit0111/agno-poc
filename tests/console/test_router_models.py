import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agno.db.sqlite import SqliteDb

import bott.interfaces.console.router as router_mod
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


def test_get_models_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/models").status_code == 403


def test_get_models_no_conflict(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    monkeypatch.setattr(models_mod, "available_models", lambda p: ["gpt-5.5", "gpt-5.5-codex"])
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()
    assert body["conflict"] is False
    assert body["swap_preview"] is None


def test_get_models_conflict_shows_swap_preview(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    import bott.shared.model as model_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5-codex",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    monkeypatch.setattr(models_mod, "available_models", lambda p: ["gpt-5.5", "gpt-5.5-codex"])
    monkeypatch.setattr(model_mod, "_review_anti_affinity", lambda model_id, provider: "gpt-5.5")
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()
    assert body["conflict"] is True
    assert body["swap_preview"] == "gpt-5.5"


def test_override_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/models", json={"key": "model.chat", "value": "gpt-5.5"})
    assert r.status_code == 403


def test_override_applies(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "apply_model_override", lambda actor, key, value: "Updated.")
    _as(client, admin=True)
    r = client.post("/api/console/v1/models", json={"key": "model.chat", "value": "gpt-5.5"})
    assert r.json() == {"message": "Updated."}


def test_connect_codex_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/models/connect-codex", json={"auth_json": "{}"})
    assert r.status_code == 403


def test_connect_codex_applies(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "connect_codex", lambda actor, auth_json: "Connected.")
    _as(client, admin=True)
    r = client.post("/api/console/v1/models/connect-codex", json={"auth_json": '{"access_token":"x"}'})
    assert r.json() == {"message": "Connected."}


def test_override_bad_key_is_400(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "apply_model_override", lambda actor, key, value: f"Unknown setting `{key}`.")
    _as(client, admin=True)
    r = client.post("/api/console/v1/models", json={"key": "model.bogus", "value": "x"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "override_failed"


def test_override_not_admin_message_is_400(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(
        models_mod, "apply_model_override",
        lambda actor, key, value: "Sorry, that's not allowed — only an admin can change the model.",
    )
    _as(client, admin=True)
    r = client.post("/api/console/v1/models", json={"key": "model.chat", "value": "x"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "override_failed"


def test_connect_codex_bad_json_is_400(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "connect_codex", lambda actor, auth_json: "Couldn't read that auth.json: Expecting value")
    _as(client, admin=True)
    r = client.post("/api/console/v1/models/connect-codex", json={"auth_json": "not json"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "connect_failed"


def test_get_models_only_fetches_active_provider_catalog(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    calls = []

    def _tracking_available_models(p):
        calls.append(p)
        return ["gpt-5.5", "gpt-5.5-codex"]

    monkeypatch.setattr(models_mod, "available_models", _tracking_available_models)
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()
    assert calls == ["codex"]
    by_name = {p["name"]: p["models"] for p in body["providers"]}
    assert by_name["openrouter"] == []
    assert by_name["bedrock"] == []
