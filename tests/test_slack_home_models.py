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


def test_models_section_is_admin_only(store):
    # Per design, the Models panel is entirely admin-only — members never see it.
    assert m.models_section(is_admin=False) == []
    assert "provider" in str(m.models_section(is_admin=True)).lower()


def test_provider_key_status(store, monkeypatch):
    monkeypatch.setattr(m.config, "openrouter_api_key", lambda: None)
    ok, hint = m.provider_key_status("openrouter")
    assert ok is False and "OPENROUTER_API_KEY" in hint
    monkeypatch.setattr(m.config, "openrouter_api_key", lambda: "k")
    ok, _ = m.provider_key_status("openrouter")
    assert ok is True


def test_available_models_codex_lists_known(store):
    assert "gpt-5.5" in m.available_models("codex")


def test_available_models_openrouter_needs_key_then_lists(store, monkeypatch):
    monkeypatch.setattr(m.config, "openrouter_api_key", lambda: None)
    assert m.available_models("openrouter") == []  # no key → no catalog
    monkeypatch.setattr(m.config, "openrouter_api_key", lambda: "k")
    monkeypatch.setattr(m, "_fetch_openrouter_models", lambda: ["anthropic/x", "openai/y"])
    assert m.available_models("openrouter") == ["anthropic/x", "openai/y"]


def test_override_admin_only(store):
    assert "not allowed" in m.apply_model_override("nobody@x.com", "model.provider", "openrouter").lower()
    from bott.shared.persistence.records import get_setting
    assert get_setting("model.provider") is None  # non-admin must NOT have written the setting
    out = m.apply_model_override("admin@axelerant.com", "model.provider", "openrouter")
    assert get_setting("model.provider") == "openrouter" and "openrouter" in out.lower()


def test_connect_codex_admin_only(store):
    import json
    bundle = json.dumps({"tokens": {"access_token": "a.b.c", "refresh_token": "r", "account_id": "acc"}})
    assert "not allowed" in m.connect_codex("nobody@x.com", bundle).lower()
    from bott.shared import codex_tokens as ct
    assert not ct.is_connected()  # non-admin must NOT have stored a token
    out = m.connect_codex("admin@axelerant.com", bundle)
    assert ct.is_connected() and ("connected" in out.lower())


def test_models_section_admin_has_set_models_button(store):
    """Admin view must include the models_set_models action button."""
    blocks = m.models_section(is_admin=True)
    action_ids = [
        el.get("action_id")
        for b in blocks
        for el in b.get("elements", [])
    ]
    assert "models_set_models" in action_ids


def test_models_section_non_admin_no_set_models_button(store):
    """Non-admin view must NOT include the models_set_models action button."""
    blocks = m.models_section(is_admin=False)
    action_ids = [
        el.get("action_id")
        for b in blocks
        for el in b.get("elements", [])
    ]
    assert "models_set_models" not in action_ids


def test_set_models_matrix_keys_written(store):
    """Submitting the matrix writes model.chat/model.build/model.review (admin-gated)."""
    from bott.shared.persistence.records import get_setting

    # Non-admin must not write anything.
    out = m.apply_model_override("nobody@x.com", "model.chat", "gpt-5.5")
    assert "not allowed" in out.lower()
    assert get_setting("model.chat") is None

    m.apply_model_override("admin@axelerant.com", "model.chat", "gpt-5.4-mini")
    r2 = m.apply_model_override("admin@axelerant.com", "model.build", "gpt-5.5-codex")
    r3 = m.apply_model_override("admin@axelerant.com", "model.review", "gpt-5.5")
    assert get_setting("model.chat") == "gpt-5.4-mini"
    assert get_setting("model.build") == "gpt-5.5-codex"
    assert get_setting("model.review") == "gpt-5.5"
    assert "gpt-5.5-codex" in r2 and "gpt-5.5" in r3


def test_set_models_warns_on_review_equals_build(store):
    m.apply_model_override("admin@axelerant.com", "model.build", "gpt-5.5")
    out = m.apply_model_override("admin@axelerant.com", "model.review", "gpt-5.5")
    assert "review = build" in out  # visible conflict warning (runtime auto-swap covers it)
