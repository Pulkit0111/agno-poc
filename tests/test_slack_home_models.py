import pytest

from bott.interfaces.slack_home import models as m
from bott.shared import db


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "h.db"))
    monkeypatch.setenv("BOTT_SECRET_KEY",
                       __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    yield


def test_active_card_always_present(store):
    blocks = m.models_section(is_admin=False)
    txt = str(blocks)
    assert "provider" in txt.lower()  # active model is shown to everyone


def test_override_admin_only(store):
    assert "not allowed" in m.apply_model_override("nobody@x.com", "model.provider", "openrouter").lower()
    out = m.apply_model_override("admin@axelerant.com", "model.provider", "openrouter")
    from bott.shared.persistence.records import get_setting
    assert get_setting("model.provider") == "openrouter" and "openrouter" in out.lower()


def test_connect_codex_admin_only(store):
    import json
    bundle = json.dumps({"tokens": {"access_token": "a.b.c", "refresh_token": "r", "account_id": "acc"}})
    assert "not allowed" in m.connect_codex("nobody@x.com", bundle).lower()
    out = m.connect_codex("admin@axelerant.com", bundle)
    from bott.shared import codex_tokens as ct
    assert ct.is_connected() and ("connected" in out.lower())
