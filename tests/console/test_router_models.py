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


def test_get_models_member_gets_trimmed_codex_status(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    _as(client, admin=False)
    body = client.get("/api/console/v1/models").json()
    assert body["active"] == {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    }
    assert body["providers"] == [{"name": "codex", "usable": True, "hint": None, "models": []}]
    assert "codex_usage" not in body
    assert "conflict" not in body


def test_get_models_member_sees_disconnected_codex(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (False, "not connected"))
    _as(client, admin=False)
    body = client.get("/api/console/v1/models").json()
    assert body["providers"][0]["usable"] is False
    assert body["providers"][0]["hint"] is None


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


# ---- Connect ChatGPT (device-auth) ---------------------------------------------------

def test_start_codex_login_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/models/codex-login/start")
    assert r.status_code == 403


def test_start_codex_login_returns_url_and_code(client, monkeypatch):
    import bott.shared.codex_login as codex_login_mod
    monkeypatch.setattr(codex_login_mod, "start_codex_login",
                        lambda: {"url": "https://auth.openai.com/device", "code": "ABCD-1234"})
    _as(client, admin=True)
    r = client.post("/api/console/v1/models/codex-login/start")
    assert r.json() == {"url": "https://auth.openai.com/device", "code": "ABCD-1234"}


def test_start_codex_login_error_is_400(client, monkeypatch):
    import bott.shared.codex_login as codex_login_mod
    monkeypatch.setattr(codex_login_mod, "start_codex_login", lambda: {"error": "already connected"})
    _as(client, admin=True)
    r = client.post("/api/console/v1/models/codex-login/start")
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "codex_login_failed"


def test_codex_login_status_requires_admin(client):
    _as(client, admin=False)
    r = client.get("/api/console/v1/models/codex-login/status")
    assert r.status_code == 403


def test_codex_login_status_reports_connection(client, monkeypatch):
    import bott.shared.codex_login as codex_login_mod
    monkeypatch.setattr(codex_login_mod, "codex_login_status", lambda: {"connected": True})
    _as(client, admin=True)
    r = client.get("/api/console/v1/models/codex-login/status")
    assert r.json() == {"connected": True}


def test_disconnect_codex_login_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/models/codex-login/disconnect")
    assert r.status_code == 403


def test_disconnect_codex_login_calls_through(client, monkeypatch):
    import bott.shared.codex_login as codex_login_mod
    called = []
    monkeypatch.setattr(codex_login_mod, "disconnect_codex_login", lambda: called.append(1))
    _as(client, admin=True)
    r = client.post("/api/console/v1/models/codex-login/disconnect")
    assert r.json() == {"connected": False}
    assert called == [1]


def test_get_models_includes_codex_usage_when_codex_is_usable(client, monkeypatch, tmp_path):
    import bott.interfaces.slack_home.models as models_mod
    from bott.shared import codex_usage, db
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "usage.db"))
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    codex_usage.record_call("U_ALICE", "gpt-5.5", 100)

    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5", "review": "gpt-5.4",
    })
    monkeypatch.setattr(models_mod, "provider_key_status",
                        lambda p: (True, "healthy") if p == "codex" else (False, "n/a"))
    monkeypatch.setattr(models_mod, "available_models", lambda p: ["gpt-5.5"])
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()
    assert body["codex_usage"]["requests"] == 1
    assert body["codex_usage"]["output_tokens"] == 100


def test_get_models_usage_is_none_when_codex_not_usable(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5", "review": "gpt-5.4",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (False, "not connected"))
    monkeypatch.setattr(models_mod, "available_models", lambda p: [])
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()
    assert body["codex_usage"] is None


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
