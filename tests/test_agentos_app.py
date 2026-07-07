import importlib
import logging

from fastapi.testclient import TestClient


def _reload_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Slack creds absent → the Slack interface + Home router stay unmounted (the app
    # constructs without them), which is what we want for a construction smoke test.
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    from bott.interfaces import app
    importlib.reload(app)
    return app


def test_agentos_app_serves_the_bott_agent(tmp_path, monkeypatch):
    app = _reload_app(tmp_path, monkeypatch)
    client = TestClient(app.app)
    assert client.get("/health").status_code == 200
    agents = client.get("/agents").json()
    # One agent with skills (no Team, no separate code-review agent).
    assert any(a.get("id") == "bott" for a in agents)


def test_os_security_key_gates_native_routes_not_own_surfaces(tmp_path, monkeypatch):
    """With OS_SECURITY_KEY set, AgentOS-native routes demand the bearer key, while the
    routes that carry their own auth (or none by design: /health, /readyz) stay open."""
    monkeypatch.setenv("OS_SECURITY_KEY", "sekrit")
    try:
        app = _reload_app(tmp_path, monkeypatch)
        client = TestClient(app.app)
        # Native routes: 401 without/with a wrong key, 200 with the right one.
        assert client.get("/agents").status_code == 401
        assert client.get("/agents", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/agents", headers={"Authorization": "Bearer sekrit"}).status_code == 200
        assert client.get("/config").status_code == 401
        # Healthchecks keep working unauthenticated (docker hits /readyz with no key).
        assert client.get("/health").status_code == 200
        assert client.get("/readyz").status_code == 200
    finally:
        # Reloads persist across tests — leave the module in the unauthenticated state
        # every other test in the suite assumes.
        monkeypatch.delenv("OS_SECURITY_KEY")
        _reload_app(tmp_path, monkeypatch)


def test_warns_at_startup_when_os_security_key_unset(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="bott.app"):
        _reload_app(tmp_path, monkeypatch)
    assert any("OS_SECURITY_KEY" in r.getMessage() for r in caplog.records)
