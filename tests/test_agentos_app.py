import importlib

from fastapi.testclient import TestClient


def _reload_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("REVIEW_DB_PATH", str(tmp_path / "store.db"))
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
