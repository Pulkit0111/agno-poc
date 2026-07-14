"""Per-role provider resolution: model.provider.<role> overrides the global
model.provider setting, which overrides the MODEL_PROVIDER env default. This lets an
admin put Chat on OpenRouter while Build/Review stay on Codex (or any other split)."""

from bott.shared import model as model_mod


def _no_setting_override(monkeypatch):
    monkeypatch.setattr(model_mod, "_setting", lambda k: None)


def test_no_overrides_falls_back_to_env_default(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)  # env default is "codex"
    assert model_mod.resolve_provider("chat") == "codex"


def test_per_role_override_beats_absent_global(monkeypatch):
    settings = {"model.provider.chat": "openrouter", "model.provider": None}
    monkeypatch.setattr(model_mod, "_setting", lambda k: settings.get(k))
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    assert model_mod.resolve_provider("chat") == "openrouter"
    assert model_mod.resolve_provider("build") == "codex"


def test_global_override_applies_to_all_roles_when_no_per_role(monkeypatch):
    monkeypatch.setattr(model_mod, "_setting", lambda k: {"model.provider": "openrouter"}.get(k))
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    assert model_mod.resolve_provider("chat") == "openrouter"
    assert model_mod.resolve_provider("build") == "openrouter"
    assert model_mod.resolve_provider("review") == "openrouter"


def test_per_role_override_beats_global(monkeypatch):
    settings = {"model.provider": "openrouter", "model.provider.build": "codex"}
    monkeypatch.setattr(model_mod, "_setting", lambda k: settings.get(k))
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    assert model_mod.resolve_provider("build") == "codex"
    assert model_mod.resolve_provider("chat") == "openrouter"


def test_per_role_override_whitespace_only_is_treated_as_absent(monkeypatch):
    settings = {"model.provider.chat": "   ", "model.provider": "openrouter"}
    monkeypatch.setattr(model_mod, "_setting", lambda k: settings.get(k))
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    assert model_mod.resolve_provider("chat") == "openrouter"


def test_build_model_chat_openrouter_build_codex_mixed_roles(monkeypatch):
    """The end-to-end split this feature exists for: chat on openrouter, build on codex,
    driven purely by per-role settings overrides."""
    settings = {"model.provider.chat": "openrouter", "model.provider": None}
    monkeypatch.setattr(model_mod, "_setting", lambda k: settings.get(k))
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(model_mod, "openrouter_api_key", lambda: "sk-x")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "x/y")

    chat = model_mod.build_model("chat")
    assert type(chat).__name__ == "OpenRouter"
    assert chat.id == "x/y"
    # Reasoning tokens are suppressed so the Slack interface doesn't render a "*Reasoning:*"
    # chain-of-thought block before the answer (reasoning.exclude keeps reasoning_content empty).
    assert chat.extra_body == {"reasoning": {"exclude": True}}

    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token", lambda: ct.CodexToken("tok", "acc"))
    monkeypatch.setenv("BOTT_BUILD_MODEL", "gpt-5.5")
    build = model_mod.build_model("build")
    assert type(build).__name__ != "OpenRouter"
    assert type(build).__name__ == "CodexModel"


def test_openrouter_model_can_override_extra_body(monkeypatch):
    """A caller-supplied extra_body wins over the reasoning-exclude default."""
    monkeypatch.setattr(model_mod, "openrouter_api_key", lambda: "sk-x")
    m = model_mod._build_for_provider("openrouter", "x/y", {"extra_body": {"custom": 1}})
    assert m.extra_body == {"custom": 1}
