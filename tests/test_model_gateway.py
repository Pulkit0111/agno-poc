import pytest

from bott.shared import model as model_mod
from bott.shared.model import build_model


def _no_setting_override(monkeypatch):
    # These tests assert the ENV-configured provider. Neutralize the DB settings-override
    # (`_setting`) so an ambient/leaked `model.provider` row in a shared DB can't flip the
    # provider out from under the test (order-independence).
    monkeypatch.setattr(model_mod, "_setting", lambda k: None)


def test_any_env_provider_still_builds_codex(monkeypatch):
    """Codex-only: a stale/unknown MODEL_PROVIDER is ignored (with a warning), never
    honored and never a crash."""
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "nope")
    assert type(build_model("chat")).__name__ == "CodexExecChat"


def test_codex_provider_builds_exec_model(monkeypatch):
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    m = model_mod.build_model("chat")
    assert m.id == "gpt-5.5"
    # codex-only architecture: the model shells out to `codex exec` — no base_url, no
    # token machinery, construction NEVER touches auth (the CLI owns CODEX_HOME).
    assert type(m).__name__ == "CodexExecChat"


def test_codex_model_carries_retry_policy(monkeypatch):
    """Regression: the codex path was built with no retries (retries=0), so a transient
    provider 500 surfaced to the user immediately as 'error, try again later' instead of
    being retried. Every provider path must carry the shared retry policy."""
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    m = model_mod.build_model("chat")
    assert m.retries >= 3
    assert m.exponential_backoff is True


def test_retry_delay_is_longer_than_a_personal_api_keys_default():
    """Regression: the old 1s base delay (1/2/4s across 3 retries — 7s total) was sized for
    a personal API key's rate limits. A whole org sharing ONE ChatGPT subscription's 429s
    often mean "wait tens of seconds," not one — the base delay must be longer than the
    library's own default of 1s."""
    assert model_mod._COMMON["delay_between_retries"] > 1


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
    assert model_mod.build_model("review").id == "gpt-5.5"


def test_codex_construction_never_touches_auth(monkeypatch):
    """The old shim resolved the org token at build_model() time — a broken login at app
    import used to crash Slack AND the console. CodexExecChat construction touches nothing:
    auth lives in CODEX_HOME and only the codex CLI reads it, per actual call."""
    _no_setting_override(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    # There is no token layer left to even stub: model.py must not import or expose one.
    assert not hasattr(model_mod, "get_valid_token")
    m = model_mod.build_model("chat")  # must not raise, must not resolve a token
    assert type(m).__name__ == "CodexExecChat"


def test_codex_broken_login_alerts_admins_on_call(monkeypatch):
    """A broken shared login must not fail silently: the first actual call alerts admins
    (throttled) and surfaces a non-retryable auth error."""
    from agno.exceptions import ModelProviderError
    from agno.models.message import Message

    from bott.shared import alerts
    from bott.shared import codex_exec_model as cem
    from bott.shared.codex_cli import CodexAuthError

    alerted = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: alerted.append(text))
    alerts._last_sent.clear()

    def fake(prompt, **kw):
        raise CodexAuthError("codex exec failed (exit 1): 401 Unauthorized: Missing bearer")

    monkeypatch.setattr(cem, "run_codex_exec", fake)
    with pytest.raises(ModelProviderError) as ei:
        cem.CodexExecChat(id="gpt-5.5").invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"))
    assert ei.value.status_code == 401
    assert alerted and "login is broken or missing" in alerted[0]


def test_stale_provider_setting_is_ignored(monkeypatch):
    """Codex-only: an old model.provider settings row must not flip anything."""
    monkeypatch.setenv("MODEL_PROVIDER", "codex")
    monkeypatch.setattr(model_mod, "_setting", lambda k: {"model.provider": "openrouter"}.get(k))
    monkeypatch.setenv("BOTT_CHAT_MODEL", "gpt-5.5")
    m = model_mod.build_model("chat")
    assert type(m).__name__ == "CodexExecChat"
    assert m.id == "gpt-5.5"
