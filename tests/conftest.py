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
