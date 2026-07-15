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
    text = str(m.models_section(is_admin=True)).lower()
    # Per-role providers, not a single global one — see test_models_section_shows_per_role_providers.
    assert "chat" in text and "build" in text and "review" in text


def test_models_section_is_codex_only(store):
    """Panel text shows the codex task→model matrix — no provider switching remains."""
    text = str(m.models_section(is_admin=True))
    assert "(codex)" in text
    assert "openrouter" not in text.lower()
    assert "bedrock" not in text.lower()


def test_provider_key_status_codex_only(store, monkeypatch):
    monkeypatch.setattr(m.codex_cli, "is_logged_in", lambda *a, **k: False)
    ok, hint = m.provider_key_status("codex")
    assert ok is False and "not connected" in hint.lower()
    ok, _ = m.provider_key_status("openrouter")
    assert ok is False  # unknown provider now


def test_available_models_codex_lists_known(store):
    assert "gpt-5.5" in m.available_models("codex")
    assert m.available_models("openrouter") == []


def test_override_admin_only(store):
    assert "not allowed" in m.apply_model_override("nobody@x.com", "model.chat", "gpt-5.4").lower()
    from bott.shared.persistence.records import get_setting
    assert get_setting("model.chat") is None  # non-admin must NOT have written the setting
    out = m.apply_model_override("admin@axelerant.com", "model.chat", "gpt-5.4")
    assert get_setting("model.chat") == "gpt-5.4" and "updated" in out.lower()


def test_provider_override_key_is_gone(store):
    """Codex-only: the provider setting keys are no longer accepted at all."""
    assert "unknown setting" in m.apply_model_override(
        "admin@axelerant.com", "model.provider", "openrouter").lower()


def test_connect_codex_admin_only(store, monkeypatch, tmp_path):
    """Pasted auth.json lands in the shared CODEX_HOME (the CLI's own store — the only
    token store), and only for admins."""
    import json
    import os
    home = str(tmp_path / "codexhome")
    monkeypatch.setenv("CODEX_HOME", home)
    bundle = json.dumps({"tokens": {"access_token": "a.b.c", "refresh_token": "r", "account_id": "acc"}})
    assert "not allowed" in m.connect_codex("nobody@x.com", bundle).lower()
    assert not os.path.exists(os.path.join(home, "auth.json"))  # non-admin wrote nothing
    out = m.connect_codex("admin@axelerant.com", bundle)
    assert "connected" in out.lower()
    written = json.loads(open(os.path.join(home, "auth.json")).read())
    assert written["tokens"]["access_token"] == "a.b.c"


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


def test_set_models_allows_review_equals_build(store):
    """Anti-affinity removed: review == build is intentional (both on the top model), so
    setting them equal must NOT warn."""
    m.apply_model_override("admin@axelerant.com", "model.build", "gpt-5.5")
    out = m.apply_model_override("admin@axelerant.com", "model.review", "gpt-5.5")
    assert "review = build" not in out
    assert "review=`gpt-5.5`" in out


def test_app_home_models_panel_is_codex_only(store):
    """Product decision: App Home offers ONLY Codex — no provider switcher, no
    Bedrock/OpenRouter connect flows. (The backend gateway still understands them.)"""
    blocks = m.models_section(is_admin=True)
    action_ids = [el.get("action_id") for b in blocks for el in b.get("elements", [])]
    assert "models_connect_codex" in action_ids
    assert "models_set_models" in action_ids
    assert "models_set_provider" not in action_ids  # provider switcher removed from Home
    rendered = str(blocks).lower()
    assert "bedrock" not in rendered and "openrouter" not in rendered


def test_provider_picker_modal_is_gone(store):
    """Codex-only: there is no provider picker modal anymore."""
    from bott.interfaces.slack_home import blocks as blocks_mod
    assert not hasattr(blocks_mod, "build_set_provider_modal")
