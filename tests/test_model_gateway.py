import pytest

from bott.shared import model as model_mod
from bott.shared.model import build_model


def _no_setting_override(monkeypatch):
    # These tests assert the ENV-configured provider. Neutralize the DB settings-override
    # (`_setting`) so an ambient/leaked `model.provider` row in a shared DB can't flip the
    # provider out from under the test (order-independence).
    monkeypatch.setattr(model_mod, "_setting", lambda k: None)


def test_openrouter_provider(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("BOTT_HEAVY_MODEL", "anthropic/claude-sonnet-4")
    m = build_model("heavy")
    assert m.id == "anthropic/claude-sonnet-4"


def test_unknown_provider_raises(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "nope")
    with pytest.raises(ValueError):
        build_model("chat")


def test_codex_provider_builds_adapter(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok-abc", "acc-1"))
    m = model_mod.build_model("chat")
    assert m.id == "gpt-5.5"
    assert "backend-api/codex" in (m.base_url or "")
    # must be the token-re-resolving CodexModel, not a plain OpenAIResponses (which would
    # freeze the token on the long-lived shared chat agent) — regression guard
    assert type(m).__name__ == "CodexModel"


def test_codex_model_carries_retry_policy(monkeypatch):
    """Regression: the codex path was built with no retries (retries=0), so a transient
    provider 500 surfaced to the user immediately as 'error, try again later' instead of
    being retried. Every provider path must carry the shared retry policy."""
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok-abc", "acc-1"))
    m = model_mod.build_model("chat")
    assert m.retries >= 3
    assert m.exponential_backoff is True


def test_openrouter_model_still_carries_retry_policy(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "x/y")
    m = model_mod.build_model("chat")
    assert m.retries >= 3
    assert m.exponential_backoff is True


def test_role_fallback_chain(monkeypatch):
    """build/review fall back to heavy, then to the single BOTT_MODEL."""
    from bott.shared.config import role_model_id
    for var in ("BOTT_BUILD_MODEL", "BOTT_REVIEW_MODEL", "BOTT_HEAVY_MODEL",
                "BOTT_CHAT_MODEL", "BOTT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert role_model_id("build") == "gpt-5.5"       # → default BOTT_MODEL
    monkeypatch.setenv("BOTT_HEAVY_MODEL", "heavy-x")
    assert role_model_id("build") == "heavy-x"       # → heavy tier
    assert role_model_id("review") == "heavy-x"
    monkeypatch.setenv("BOTT_BUILD_MODEL", "build-y")
    monkeypatch.setenv("BOTT_REVIEW_MODEL", "review-z")
    assert role_model_id("build") == "build-y"       # → own env wins
    assert role_model_id("review") == "review-z"


def test_anti_affinity_never_picks_codex_suffixed_alternate(monkeypatch):
    """The ChatGPT-account Codex backend rejects '-codex' model ids ("not supported when
    using Codex with a ChatGPT account") — the swap must skip them, or the 'fix' breaks
    every review. build=gpt-5.5 → alternate must be gpt-5.4, NOT gpt-5.5-codex."""
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    for var in ("BOTT_BUILD_MODEL", "BOTT_REVIEW_MODEL", "BOTT_CHAT_MODEL",
                "BOTT_HEAVY_MODEL", "BOTT_MODEL"):
        monkeypatch.delenv(var, raising=False)   # everything defaults to gpt-5.5
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok", "acc"))
    review = model_mod.build_model("review")
    assert review.id != "gpt-5.5"                 # swapped away from build
    assert not review.id.endswith("-codex")       # never onto a backend-rejected id


def test_review_anti_affinity_swaps_model(monkeypatch):
    """The reviewer must not be the model that wrote the code: when review resolves to the
    same id as build, build_model('review') swaps to an alternate (codex catalog)."""
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    for var in ("BOTT_BUILD_MODEL", "BOTT_REVIEW_MODEL", "BOTT_CHAT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BOTT_HEAVY_MODEL", "gpt-5.5-codex")  # build == review == same id
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok", "acc"))
    build = model_mod.build_model("build")
    review = model_mod.build_model("review")
    assert build.id == "gpt-5.5-codex"
    assert review.id != build.id                     # swapped
    from bott.shared.config import FALLBACK_CODEX_MODELS
    assert review.id in FALLBACK_CODEX_MODELS


def test_review_no_swap_when_models_differ(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_BUILD_MODEL", "gpt-5.5-codex")
    monkeypatch.setenv("BOTT_REVIEW_MODEL", "gpt-5.5")
    from bott.shared import codex_tokens as ct
    monkeypatch.setattr(model_mod, "get_valid_token",
                        lambda: ct.CodexToken("tok", "acc"))
    assert model_mod.build_model("review").id == "gpt-5.5"


def test_codex_not_connected_propagates(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    from bott.shared import codex_tokens as ct
    def boom(): raise ct.CodexNotConnected("nope")
    monkeypatch.setattr(model_mod, "get_valid_token", boom)
    with pytest.raises(ct.CodexNotConnected):
        model_mod.build_model("chat")


def test_settings_override_beats_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setattr(model_mod, "_setting", lambda k: {"model.provider": "openrouter"}.get(k))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "x/y")
    m = model_mod.build_model("chat")
    assert m.id == "x/y"  # OpenRouter model built because settings overrode provider
