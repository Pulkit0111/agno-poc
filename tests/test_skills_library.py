from bott.agents import bott_agent


def test_skills_load_and_include_advisories():
    skills = bott_agent.build_skills()
    names = skills.get_skill_names()
    assert "security-advisories" in names


def test_discovery_snippet_mentions_advisories():
    skills = bott_agent.build_skills()
    snippet = skills.get_system_prompt_snippet()
    assert "security-advisories" in snippet


def test_all_six_skills_present():
    skills = bott_agent.build_skills()
    names = set(skills.get_skill_names())
    assert {"pr-review", "dsm", "sprint-report", "portfolio", "concierge", "security-advisories"} <= names


def test_library_is_the_curated_six():
    from bott.agents.bott_agent import build_skills
    names = set(build_skills().get_skill_names())
    assert names == {"pr-review", "dsm", "sprint-report", "portfolio", "concierge", "security-advisories"}
