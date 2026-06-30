import pytest

from bott.agents.build_fix.refs import BuildRequest, parse_build_target


def test_github_issue_ref():
    r = parse_build_target("octo/repo#123")
    assert r.kind == "github_issue" and r.owner == "octo" and r.repo == "repo" and r.issue == 123


def test_github_issue_url():
    r = parse_build_target("https://github.com/octo/repo/issues/123")
    assert r.kind == "github_issue" and r.owner == "octo" and r.repo == "repo" and r.issue == 123


def test_jira_key():
    r = parse_build_target("PADI-42")
    assert r.kind == "jira" and r.jira_key == "PADI-42"


def test_plain_request():
    r = parse_build_target("add a /health endpoint to octo/repo")
    assert r.kind == "request" and "health" in r.text


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_is_request_with_empty_text(blank):
    r = parse_build_target(blank)
    assert r.kind == "request"
