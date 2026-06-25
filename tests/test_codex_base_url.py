"""In codex backend mode the model base URL must come from CODEX_PROXY_PORT (single source
of truth), so a second instance on a different proxy port never calls the wrong port."""

from bott.shared import config


def test_codex_backend_derives_base_url_from_proxy_port(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "codex")
    monkeypatch.setenv("CODEX_PROXY_PORT", "10541")
    # A stale hardcoded value must be IGNORED in codex mode (this was the workspace-B bug).
    monkeypatch.setenv("MANAGER_MODEL_BASE_URL", "http://127.0.0.1:10531/v1")
    monkeypatch.setenv("REVIEW_MODEL_BASE_URL", "http://127.0.0.1:10531/v1")
    assert config.manager_base_url() == "http://127.0.0.1:10541/v1"
    assert config.model_base_url() == "http://127.0.0.1:10541/v1"


def test_openai_backend_uses_env_base_url(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "openai")
    monkeypatch.setenv("MANAGER_MODEL_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("REVIEW_MODEL_BASE_URL", "https://api.example.com/v1")
    assert config.manager_base_url() == "https://api.example.com/v1"
    assert config.model_base_url() == "https://api.example.com/v1"


def test_openai_backend_none_when_unset(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "openai")
    monkeypatch.delenv("MANAGER_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("REVIEW_MODEL_BASE_URL", raising=False)
    assert config.manager_base_url() is None
    assert config.model_base_url() is None
