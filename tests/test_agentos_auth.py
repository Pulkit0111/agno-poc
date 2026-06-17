import importlib
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

SECRET = "test-secret-at-least-256-bits-long-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("AGENT_OS_JWT_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from bott.interfaces import agentos
    importlib.reload(agentos)
    return TestClient(agentos.app)


def test_agents_requires_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/agents").status_code == 401


def test_agents_accepts_minted_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    token = jwt.encode(
        {
            "sub": "u@axelerant.com", "email": "u@axelerant.com", "hd": "axelerant.com",
            "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        SECRET, algorithm="HS256",
    )
    r = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_health_is_public_even_with_auth(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200
