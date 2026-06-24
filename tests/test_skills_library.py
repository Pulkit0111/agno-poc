# tests/test_skills_library.py
from bott.agents import bott_agent


def test_skills_load_and_include_advisories():
    skills = bott_agent.build_skills()
    names = skills.get_skill_names()
    assert "security-advisories" in names


def test_discovery_snippet_mentions_advisories():
    skills = bott_agent.build_skills()
    snippet = skills.get_system_prompt_snippet()
    assert "security-advisories" in snippet
