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
