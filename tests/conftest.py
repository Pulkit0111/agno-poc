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

# BOTT_ADMINS from a real .env is a real person's email — leaking it into tests that
# assume no admins are configured produces spurious, environment-dependent failures/passes
# depending on whoever's machine runs the suite. Suppressed for the same reason as MEMRA_*.
_ADMIN_ENV_KEYS = ("BOTT_ADMINS",)

# CODEX_CLI_EXEC / BOTT_CODEX_DISABLE_SANDBOX flip build/review onto the codex-exec subprocess
# path. A real .env that sets CODEX_CLI_EXEC=1 must NOT silently redirect the Agno-path tests
# (which inject a fake agno Agent and assert it ran) onto the CLI branch — that's an
# environment-dependent failure exactly like MEMRA_*/BOTT_ADMINS. Suppressed by default; the
# CLI-path test modules opt back in via their own `monkeypatch.setenv("CODEX_CLI_EXEC","1")`
# autouse fixtures, which run after this one.
_CODEX_EXEC_ENV_KEYS = ("CODEX_CLI_EXEC", "BOTT_CODEX_DISABLE_SANDBOX")


_pg_cleanup_engine = None


def _get_pg_cleanup_engine(url: str):
    """A dedicated engine connected straight to TEST_DATABASE_URL, independent of the
    shared get_engine() singleton — which reads DATABASE_URL (a DIFFERENT env var each
    individual test's own fixture sets up, generally after this one runs). Reusing the
    shared engine here would mean truncating whatever get_engine() happens to currently
    resolve to (often a stale local SQLite file, not Postgres at all) rather than the
    Postgres database this fixture actually means to clean."""
    global _pg_cleanup_engine
    if _pg_cleanup_engine is None:
        from sqlalchemy import create_engine
        # Same normalization as db.py's get_engine(): the project installs psycopg (v3),
        # not psycopg2, but a bare "postgresql://" URL makes SQLAlchemy default to the
        # psycopg2 driver and raise ModuleNotFoundError.
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        _pg_cleanup_engine = create_engine(url)
    return _pg_cleanup_engine


@pytest.fixture(autouse=True)
def _clean_postgres_between_tests():
    """Give every test the same "starts empty" guarantee on Postgres that it already gets
    for free on SQLite.

    On the default SQLite path, most tests point AGENTOS_DB_PATH at their own tmp_path
    file, so each test starts with a genuinely fresh, empty database. On the opt-in
    TEST_DATABASE_URL path (a real Postgres, used to catch Postgres-only SQL issues our
    default SQLite runs can't), every test's `db.get_engine(fresh=True)` reconnects to the
    SAME shared database instead — so one test's rows leaked into the next test's counts
    and lists (confirmed: ~26 spurious failures across action-items/prompts/policy-
    overrides/review-trends/records tests, none of them touching anything Postgres-
    specific). A no-op on the SQLite path; only truncates when TEST_DATABASE_URL is set.
    """
    import os
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        yield
        return
    from sqlalchemy import text

    from bott.shared.schema import METADATA, init_schema
    engine = _get_pg_cleanup_engine(url)
    init_schema(engine)
    table_names = ", ".join(t.name for t in METADATA.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture(autouse=True)
def _reset_connector_registry(monkeypatch):
    """Reset the process-wide connector REGISTRY before each test so that tests
    that call build_agent() or register_all() don't pollute subsequent tests.

    Also clears MEMRA/admin env vars that may have been loaded from .env by
    test_app_constructs (which imports bott.interfaces.app at module level,
    triggering dotenv load). Tests that explicitly need Memra or specific admins
    must monkeypatch config directly — see test_portfolio_dashboard.py.
    """
    import os

    from bott.skills.connectors.registry import REGISTRY
    REGISTRY._reset()
    # Suppress MEMRA/admin env vars so memra_configured()/bott_admins() are empty by
    # default across all tests. Tests that need them set/monkeypatch explicitly, which
    # overrides this env-level suppression.
    saved = {k: os.environ.pop(k, None)
             for k in (*_MEMRA_ENV_KEYS, *_ADMIN_ENV_KEYS, *_CODEX_EXEC_ENV_KEYS)}
    yield
    REGISTRY._reset()
    # Restore for any subsequent test that truly depends on them.
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
