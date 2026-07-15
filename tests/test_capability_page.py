"""Tests for bott.skills.capability_page."""

from __future__ import annotations

from pathlib import Path

import bott.skills.capability_page as cap_mod
from bott.skills.capability_page import capability_page, capability_page_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANNED_LINK = "Published: https://bott-capabilities.public.spin.axelerant.tech — share this link with the user."


def _make_skills_dir(tmp_path: Path, skills: list[dict]) -> Path:
    """Write a temporary skills directory with one SKILL.md per skill entry."""
    skills_root = tmp_path / "library"
    for entry in skills:
        slug = entry["name"].replace(" ", "-").lower()
        skill_dir = skills_root / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {entry['name']}\ndescription: {entry['description']}\n---\n\n# Body\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skills_root


def _patch_all(
    monkeypatch,
    *,
    spin=True,
    connector_names=None,
    skills=None,
    repos=None,
    model=None,
    publish_spy=None,
):
    """Monkeypatch every external seam that capability_page touches."""
    if connector_names is None:
        connector_names = {"org": ["jira", "confluence"], "user": ["gmail", "drive"]}
    if repos is None:
        repos = {"axelerant/my-project", "axelerant/another-repo"}
    if model is None:
        model = {"provider": "openai", "chat": "gpt-4o", "heavy": "gpt-4o"}
    if publish_spy is None:
        publish_spy = lambda **kw: _CANNED_LINK  # noqa: E731

    monkeypatch.setattr(cap_mod.config, "spin_configured", lambda: spin)

    # Patch register_all to a no-op and REGISTRY.list_names to return canned data
    monkeypatch.setattr(cap_mod, "register_all", lambda: None, raising=False)

    # We patch the module-level names used inside capability_page() via lazy imports.
    # Since the function does local imports, monkeypatch on the sub-modules directly.
    import bott.skills.connectors.registry as reg_mod

    monkeypatch.setattr(reg_mod.REGISTRY, "list_names", lambda: connector_names)

    monkeypatch.setattr(cap_mod.config, "allowed_post_repos", lambda: repos)

    import bott.interfaces.slack_home.models as models_mod

    monkeypatch.setattr(models_mod, "_active", lambda: model)

    # publish_web_page and _brand_wrap live in web_publish; patch them in cap_mod's namespace
    # by patching cap_mod's local reference after it's been imported once.
    # Because cap_mod does local `from bott.skills.web_publish import ...` inside the function,
    # we patch the source module directly.
    import bott.skills.web_publish as wp_mod

    calls = []

    def _spy_publish(name, html="", **kw):
        calls.append({"name": name, "html": html})
        return _CANNED_LINK

    if publish_spy is not None:
        monkeypatch.setattr(wp_mod, "publish_web_page", _spy_publish)

    return calls


# ---------------------------------------------------------------------------
# Skill lookup helper
# ---------------------------------------------------------------------------

def test_read_skill_entries_parses_name_and_description(tmp_path):
    from bott.skills.capability_page import _read_skill_entries

    skills_root = _make_skills_dir(tmp_path, [
        {"name": "sprint-report", "description": "Publish a sprint report."},
        {"name": "dsm", "description": "DSM standup support."},
    ])
    entries = _read_skill_entries(str(skills_root))
    names = [e["name"] for e in entries]
    assert "sprint-report" in names
    assert "dsm" in names
    assert any(e["description"] == "Publish a sprint report." for e in entries)


def test_read_skill_entries_empty_dir(tmp_path):
    from bott.skills.capability_page import _read_skill_entries

    entries = _read_skill_entries(str(tmp_path / "nonexistent"))
    assert entries == []


# ---------------------------------------------------------------------------
# Gate: spin_configured() is False
# ---------------------------------------------------------------------------

def test_spin_not_configured_returns_message_no_publish(monkeypatch):
    calls = _patch_all(monkeypatch, spin=False)
    result = capability_page()
    assert "SPIN_API_TOKEN" in result
    assert "can't host" in result
    assert calls == [], "publish_web_page must NOT be called when Spin is not configured"


# ---------------------------------------------------------------------------
# Happy path: configured
# ---------------------------------------------------------------------------

def test_publish_called_once_when_configured(monkeypatch, tmp_path):
    calls = _patch_all(monkeypatch, spin=True)

    # Point skills dir at a real tmp dir
    skills_root = _make_skills_dir(tmp_path, [
        {"name": "sprint-report", "description": "Publish an engagement's full sprint report."},
        {"name": "dsm", "description": "DSM standup support."},
    ])
    monkeypatch.setattr(cap_mod.config, "bott_skills_dir", lambda: str(skills_root))

    result = capability_page()

    assert len(calls) == 1, "publish_web_page must be called exactly once"
    assert calls[0]["name"] == "bott-capabilities"
    assert result == _CANNED_LINK


def test_html_contains_connector_names(monkeypatch, tmp_path):
    connector_names = {"org": ["jira", "sentry"], "user": ["gmail"]}
    calls = _patch_all(monkeypatch, spin=True, connector_names=connector_names)

    skills_root = _make_skills_dir(tmp_path, [{"name": "my-skill", "description": "Does stuff."}])
    monkeypatch.setattr(cap_mod.config, "bott_skills_dir", lambda: str(skills_root))

    capability_page()

    html = calls[0]["html"]
    assert "jira" in html
    assert "sentry" in html
    assert "gmail" in html


def test_html_contains_skill_name_and_description(monkeypatch, tmp_path):
    calls = _patch_all(monkeypatch, spin=True)

    skills_root = _make_skills_dir(tmp_path, [
        {"name": "sprint-report", "description": "Publish the weekly sprint report."},
    ])
    monkeypatch.setattr(cap_mod.config, "bott_skills_dir", lambda: str(skills_root))

    capability_page()

    html = calls[0]["html"]
    assert "sprint-report" in html
    assert "Publish the weekly sprint report." in html


def test_html_contains_repo_names(monkeypatch, tmp_path):
    repos = {"axelerant/client-alpha", "axelerant/platform"}
    calls = _patch_all(monkeypatch, spin=True, repos=repos)

    skills_root = _make_skills_dir(tmp_path, [{"name": "s", "description": "d."}])
    monkeypatch.setattr(cap_mod.config, "bott_skills_dir", lambda: str(skills_root))

    capability_page()

    html = calls[0]["html"]
    assert "axelerant/client-alpha" in html
    assert "axelerant/platform" in html


def test_html_contains_model_provider(monkeypatch, tmp_path):
    model = {"provider": "bedrock", "chat": "claude-3-haiku", "heavy": "claude-3-opus"}
    calls = _patch_all(monkeypatch, spin=True, model=model)

    skills_root = _make_skills_dir(tmp_path, [{"name": "s", "description": "d."}])
    monkeypatch.setattr(cap_mod.config, "bott_skills_dir", lambda: str(skills_root))

    capability_page()

    html = calls[0]["html"]
    assert "bedrock" in html


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------

def test_publish_exception_returns_friendly_message(monkeypatch, tmp_path):
    """If publish_web_page raises, returns a friendly string (not a traceback)."""
    _patch_all(monkeypatch, spin=True)

    import bott.skills.web_publish as wp_mod

    monkeypatch.setattr(wp_mod, "publish_web_page", lambda **kw: (_ for _ in ()).throw(RuntimeError("Spin down")))

    skills_root = _make_skills_dir(tmp_path, [{"name": "s", "description": "d."}])
    monkeypatch.setattr(cap_mod.config, "bott_skills_dir", lambda: str(skills_root))

    result = capability_page()
    assert "Couldn't publish" in result


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def test_capability_page_tools_returns_callable():
    tools = capability_page_tools()
    assert len(tools) == 1
    assert callable(tools[0])
    assert tools[0].__name__ == "capability_page"


# ---------------------------------------------------------------------------
# build_agent includes capability_page
# ---------------------------------------------------------------------------

def test_build_agent_includes_capability_page():
    # Chat tools are served over MCP now — the surface lives in build_chat_toolkits.
    from bott.agents.bott_agent import build_chat_toolkits

    tool_names = []
    for t in build_chat_toolkits(db=None):
        name = getattr(t, "__name__", None) or getattr(t, "name", None) or str(t)
        tool_names.append(name)
    assert "capability_page" in tool_names
