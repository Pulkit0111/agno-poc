import importlib

from fastapi.testclient import TestClient


def _reload_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "os.db"))
    monkeypatch.setenv("REVIEW_DB_PATH", str(tmp_path / "store.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_OS_JWT_SECRET", "")  # open API for the test
    import bott.shared.persistence.store as store

    store.DB_FILE = str(tmp_path / "store.db")  # the settings KV lives here
    from bott.interfaces import agentos
    importlib.reload(agentos)
    return agentos


def test_settings_roundtrip_and_models(tmp_path, monkeypatch):
    agentos = _reload_app(tmp_path, monkeypatch)
    client = TestClient(agentos.app)

    models = client.get("/bott/models").json()
    assert "models" in models and isinstance(models["models"], list)
    assert "manager_model" in models and "reviewer_model" in models

    r = client.post(
        "/bott/settings",
        json={"manager_model": "gpt-5.4-mini", "reviewer_model": "gpt-5.5"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["manager_model"] == "gpt-5.4-mini"
    assert body["reviewer_model"] == "gpt-5.5"

    # persisted
    assert client.get("/bott/settings").json()["reviewer_model"] == "gpt-5.5"


def test_settings_kv_store(tmp_path, monkeypatch):
    import bott.shared.persistence.store as store

    store.DB_FILE = str(tmp_path / "kv.db")
    assert store.get_setting("manager_model") is None
    store.set_setting("manager_model", "gpt-5.5")
    assert store.get_setting("manager_model") == "gpt-5.5"
