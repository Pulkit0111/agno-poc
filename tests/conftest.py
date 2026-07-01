"""Shared test fixtures.

Auto-patch get_valid_token for the lifetime of every test so that constructing
the Bott agent (which calls build_model("chat") → get_valid_token() in the
default codex provider path) never hits the database.  Tests that need specific
token behaviour (test_model_gateway.py) override this fixture with their own
monkeypatch.setattr call, which takes effect after conftest runs.
"""

from __future__ import annotations

import pytest

from bott.shared import model as _model_mod
from bott.shared.codex_tokens import CodexToken


@pytest.fixture(autouse=True)
def _stub_codex_token(monkeypatch):
    """Return a synthetic token for all tests; individual tests may override."""
    monkeypatch.setattr(
        _model_mod,
        "get_valid_token",
        lambda: CodexToken("sk-stub-token", "acc-stub"),
    )


_MEMRA_ENV_KEYS = (
    "MEMRA_CLIENT_ID",
    "MEMRA_CLIENT_SECRET",
    "MEMRA_TOKEN_ENDPOINT",
    "MEMRA_MCP_ENDPOINT",
    "MEMRA_SCOPE",
)


@pytest.fixture(autouse=True)
def _reset_connector_registry(monkeypatch):
    """Reset the process-wide connector REGISTRY before each test so that tests
    that call build_agent() or register_all() don't pollute subsequent tests.

    Also clears MEMRA env vars that may have been loaded from .env by
    test_app_constructs (which imports bott.interfaces.app at module level,
    triggering dotenv load). Tests that explicitly need Memra enabled must
    monkeypatch memra_configured themselves — see test_portfolio_dashboard.py.
    """
    import os
    from bott.skills.connectors.registry import REGISTRY
    REGISTRY._reset()
    # Suppress MEMRA env vars so memra_configured() is False by default across
    # all tests.  Tests that need Memra monkeypatch config.memra_configured
    # directly, which overrides this env-level suppression.
    saved = {k: os.environ.pop(k, None) for k in _MEMRA_ENV_KEYS}
    yield
    REGISTRY._reset()
    # Restore MEMRA env vars for any subsequent test that truly depends on them.
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
