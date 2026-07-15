"""Members need the task->model matrix (chat/build/review ids) to render the Home-page
model card. They must NOT get codex_usage, key hints, or the model catalog — those stay
admin-only. See src/bott/interfaces/slack_home/models.py:_active() for the matrix source."""
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


def test_member_gets_task_model_matrix_ids_only(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    _as(client, admin=False)
    body = client.get("/api/console/v1/models").json()

    assert isinstance(body["active"]["chat"], str) and body["active"]["chat"]
    assert isinstance(body["active"]["build"], str) and body["active"]["build"]
    assert isinstance(body["active"]["review"], str) and body["active"]["review"]

    # Global constraint: no usage, no key hints, no catalog for members.
    assert "codex_usage" not in body
    assert "catalog" not in body
    for p in body["providers"]:
        assert p["models"] == []
        assert p.get("hint") is None


def test_admin_payload_still_has_everything_it_had(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    monkeypatch.setattr(models_mod, "provider_key_status", lambda p: (True, "healthy"))
    monkeypatch.setattr(models_mod, "available_models", lambda p: ["gpt-5.5", "gpt-5.5-codex"])
    _as(client, admin=True)
    body = client.get("/api/console/v1/models").json()

    assert body["provider"] == "codex"
    assert body["chat"] == "gpt-5.5"
    assert body["build"] == "gpt-5.5-codex"
    assert body["review"] == "gpt-5.5"
    assert "conflict" in body
    assert "swap_preview" in body
    assert "providers" in body
    assert "codex_usage" in body
