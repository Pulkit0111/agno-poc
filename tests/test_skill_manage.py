from bott.agents import bott_agent
from bott.skills import workspace_tools


def test_create_then_reload_makes_skill_discoverable(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_SKILLS_DIR", str(tmp_path / "library"))
    skills = bott_agent.build_skills()
    body = "---\nname: launch-checklist\ndescription: Draft a launch checklist.\n---\n# Launch\nSteps."
    out = workspace_tools._skill_manage_impl(skills, "create", "launch-checklist", body)
    assert "launch-checklist" in out
    assert "launch-checklist" in skills.get_skill_names()


def test_list_returns_names(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_SKILLS_DIR", str(tmp_path / "library"))
    skills = bott_agent.build_skills()
    workspace_tools._skill_manage_impl(
        skills, "create", "x-skill", "---\nname: x-skill\ndescription: d\n---\n# X"
    )
    listing = workspace_tools._skill_manage_impl(skills, "list", "")
    assert "x-skill" in listing


def test_skill_manage_reports_failure_if_not_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_SKILLS_DIR", str(tmp_path / "library"))
    from bott.agents.bott_agent import build_skills
    from bott.skills import workspace_tools
    skills = build_skills()
    # reload is a no-op here → skill won't appear → must NOT claim success
    monkeypatch.setattr(skills, "reload", lambda: None)
    out = workspace_tools._skill_manage_impl(
        skills, "create", "ghost", "---\nname: ghost\ndescription: d\n---\n# g")
    assert "available now" not in out.lower()
