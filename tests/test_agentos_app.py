import importlib

from fastapi.testclient import TestClient


def _reload_app(tmp_path, monkeypatch, *, secret=None):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    if secret is None:
        monkeypatch.delenv("AGENT_OS_JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("AGENT_OS_JWT_SECRET", secret)
    from bott.interfaces import agentos
    importlib.reload(agentos)
    return agentos


def test_agentos_lists_agents_and_team(tmp_path, monkeypatch):
    agentos = _reload_app(tmp_path, monkeypatch)  # no secret → open API
    client = TestClient(agentos.app)
    assert client.get("/health").status_code == 200
    agents = client.get("/agents").json()
    assert any(a.get("id") == "code-review" for a in agents)
    teams = client.get("/teams").json()
    assert any(t.get("id") == "bott-manager" for t in teams)
