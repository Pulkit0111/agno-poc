import pytest

from bott.agents.build_fix.refs import parse_build_target


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


# --- Fix 1: bare-repo recognition ---

def test_bare_repo_url_sets_owner_and_repo():
    r = parse_build_target("https://github.com/Pulkit0111/bott-pr-review-harness")
    assert r.kind == "request"
    assert r.owner == "Pulkit0111" and r.repo == "bott-pr-review-harness"


def test_bare_repo_url_dotgit():
    r = parse_build_target("https://github.com/Pulkit0111/bott-pr-review-harness.git")
    assert r.kind == "request"
    assert r.owner == "Pulkit0111" and r.repo == "bott-pr-review-harness"


def test_prose_with_owner_repo_sets_owner_and_repo():
    r = parse_build_target("open a PR on Pulkit0111/bott-pr-review-harness")
    assert r.kind == "request"
    assert r.owner == "Pulkit0111" and r.repo == "bott-pr-review-harness"
    assert "open a PR" in r.text


def test_issue_ref_still_github_issue():
    r = parse_build_target("octo/repo#5")
    assert r.kind == "github_issue" and r.owner == "octo" and r.repo == "repo" and r.issue == 5


def test_jira_key_not_misclassified_as_repo():
    r = parse_build_target("PADI-42")
    assert r.kind == "jira"


def test_pure_prose_no_repo_stays_request_with_no_owner():
    r = parse_build_target("please add a health check endpoint")
    assert r.kind == "request"
    assert r.owner is None and r.repo is None
