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


def test_curated_skills_present():
    """The curated core skills must all load. Self-authored skills (skill_manage) legitimately
    ADD to the library at runtime, so we assert the core is a subset — not an exact match."""
    from bott.agents.bott_agent import build_skills
    names = set(build_skills().get_skill_names())
    core = {"pr-review", "dsm", "sprint-report", "portfolio", "concierge", "security-advisories"}
    assert core <= names, f"missing curated skills: {core - names}"
