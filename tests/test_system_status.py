"""Tests for bott.skills.system_status."""

from __future__ import annotations

from bott.skills import system_status as ss_mod
from bott.skills.system_status import system_status, system_status_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_all(monkeypatch, *, provider="openai", chat="gpt-4o", build="gpt-4o",
               review="gpt-4o-mini", codex=False, database_url=None, jira=False,
               confluence=False, sentry=False, memra=False, spin=False, google=False,
               github_app=False, admins=None):
    """Monkeypatch everything system_status touches to known values."""
    monkeypatch.setattr(ss_mod, "_active",
                        lambda: {"provider": provider, "chat": chat, "build": build,
                                 "review": review})
    monkeypatch.setattr(ss_mod.codex_tokens, "is_connected", lambda: codex)
    monkeypatch.setattr(ss_mod.config, "database_url", lambda: database_url)
    monkeypatch.setattr(ss_mod.config, "jira_configured", lambda: jira)
    monkeypatch.setattr(ss_mod.config, "confluence_configured", lambda: confluence)
    monkeypatch.setattr(ss_mod.config, "sentry_configured", lambda: sentry)
    monkeypatch.setattr(ss_mod.config, "memra_configured", lambda: memra)
    monkeypatch.setattr(ss_mod.config, "spin_configured", lambda: spin)
    monkeypatch.setattr(ss_mod.config, "google_delegation_configured", lambda: google)
    monkeypatch.setattr(ss_mod.config, "github_app_configured", lambda: github_app)
    monkeypatch.setattr(ss_mod.config, "bott_admins", lambda: set(admins or []))


# ---------------------------------------------------------------------------
# Model section
# ---------------------------------------------------------------------------

def test_model_matrix_shown(monkeypatch):
    _patch_all(monkeypatch, provider="bedrock", chat="claude-3-sonnet",
               build="claude-3-opus", review="claude-3-sonnet")
    out = system_status()
    assert "bedrock" in out
    assert "claude-3-sonnet" in out
    assert "claude-3-opus" in out


def test_model_matrix_warns_when_review_equals_build(monkeypatch):
    _patch_all(monkeypatch, build="same-model", review="same-model")
    assert "review = build" in system_status()


def test_codex_connected(monkeypatch):
    _patch_all(monkeypatch, codex=True)
    out = system_status()
    assert "Org Codex" in out
    assert "connected" in out
    assert "not connected" not in out


def test_codex_not_connected(monkeypatch):
    _patch_all(monkeypatch, codex=False)
    out = system_status()
    assert "not connected" in out


# ---------------------------------------------------------------------------
# Database section
# ---------------------------------------------------------------------------

def test_postgres_when_database_url_set(monkeypatch):
    _patch_all(monkeypatch, database_url="postgresql://user:pass@host/db")
    out = system_status()
    assert "Postgres" in out
    assert "SQLite" not in out


def test_sqlite_when_database_url_absent(monkeypatch):
    _patch_all(monkeypatch, database_url=None)
    out = system_status()
    assert "SQLite" in out


# ---------------------------------------------------------------------------
# Connectors — configured vs not
# ---------------------------------------------------------------------------

def test_jira_configured(monkeypatch):
    _patch_all(monkeypatch, jira=True)
    out = system_status()
    assert "✅ Jira" in out


def test_jira_not_configured(monkeypatch):
    _patch_all(monkeypatch, jira=False)
    out = system_status()
    assert "⚠️  Jira" in out
    assert "JIRA_BASE_URL" in out


def test_confluence_configured(monkeypatch):
    _patch_all(monkeypatch, confluence=True)
    out = system_status()
    assert "✅ Confluence" in out


def test_confluence_not_configured(monkeypatch):
    _patch_all(monkeypatch, confluence=False)
    out = system_status()
    assert "⚠️  Confluence" in out


def test_sentry_configured(monkeypatch):
    _patch_all(monkeypatch, sentry=True)
    out = system_status()
    assert "✅ Sentry" in out


def test_sentry_not_configured_hint(monkeypatch):
    _patch_all(monkeypatch, sentry=False)
    out = system_status()
    assert "⚠️  Sentry" in out
    assert "SENTRY_ORG_SLUG" in out
    assert "SENTRY_API_TOKEN" in out


def test_memra_configured(monkeypatch):
    _patch_all(monkeypatch, memra=True)
    out = system_status()
    assert "✅ Memra" in out


def test_memra_not_configured(monkeypatch):
    _patch_all(monkeypatch, memra=False)
    out = system_status()
    assert "⚠️  Memra" in out


def test_spin_configured(monkeypatch):
    _patch_all(monkeypatch, spin=True)
    out = system_status()
    assert "✅ Spin" in out


def test_spin_not_configured(monkeypatch):
    _patch_all(monkeypatch, spin=False)
    out = system_status()
    assert "⚠️  Spin" in out


# ---------------------------------------------------------------------------
# Google — the "connect gmail" education fix
# ---------------------------------------------------------------------------

def test_google_configured(monkeypatch):
    _patch_all(monkeypatch, google=True)
    out = system_status()
    assert "✅ Google" in out
    assert "read-only" in out
    assert "impersonating" in out


def test_google_not_configured_org_admin_explanation(monkeypatch):
    """The unconfigured Google line must teach that there's no per-user connect step."""
    _patch_all(monkeypatch, google=False)
    out = system_status()
    # Correct model explained — no per-user "connect"
    assert "no per-user" in out
    assert "Workspace admin" in out
    assert "GOOGLE_SERVICE_ACCOUNT_PATH" in out
    assert "readonly" in out


# ---------------------------------------------------------------------------
# GitHub App
# ---------------------------------------------------------------------------

def test_github_app_configured(monkeypatch):
    _patch_all(monkeypatch, github_app=True)
    out = system_status()
    assert "✅ GitHub App" in out


def test_github_app_not_configured(monkeypatch):
    _patch_all(monkeypatch, github_app=False)
    out = system_status()
    assert "⚠️  GitHub App" in out
    assert "GITHUB_APP_ID" in out


# ---------------------------------------------------------------------------
# Scheduler / Admins
# ---------------------------------------------------------------------------

def test_scheduler_always_on(monkeypatch):
    _patch_all(monkeypatch)
    out = system_status()
    assert "Scheduler: on" in out


def test_admins_count(monkeypatch):
    _patch_all(monkeypatch, admins=["a@x.com", "b@x.com"])
    out = system_status()
    assert "Admins configured: 2" in out


def test_no_admins_warning(monkeypatch):
    _patch_all(monkeypatch, admins=[])
    out = system_status()
    assert "No admins" in out
    assert "BOTT_ADMINS" in out


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def test_system_status_tools_returns_callable():
    tools = system_status_tools()
    assert len(tools) == 1
    assert callable(tools[0])
    assert tools[0].__name__ == "system_status"


# ---------------------------------------------------------------------------
# build_agent includes system_status (optional integration smoke test)
# ---------------------------------------------------------------------------

def test_build_agent_includes_system_status():
    # Chat tools are served over MCP now — the surface lives in build_chat_toolkits.
    from bott.agents.bott_agent import build_chat_toolkits

    tool_names = []
    for t in build_chat_toolkits(db=None):
        # Plain callables have __name__; Agno tool wrappers may have .name
        name = getattr(t, "__name__", None) or getattr(t, "name", None) or str(t)
        tool_names.append(name)
    assert "system_status" in tool_names
