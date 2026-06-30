"""Task 8: planning helper tests for draft_plan_text."""
from bott.agents.build_fix.planning import draft_plan_text


def test_request_uses_text():
    assert draft_plan_text({"kind": "request", "text": "add a /health endpoint"}) == "add a /health endpoint"


def test_github_issue_references_source():
    out = draft_plan_text({"kind": "github_issue", "owner": "o", "repo": "r", "issue": 5})
    assert "o/r#5" in out


def test_jira_references_key():
    assert "PADI-42" in draft_plan_text({"kind": "jira", "jira_key": "PADI-42"})
