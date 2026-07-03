import pytest

from bott.agents.build_fix.refs import parse_build_target, parse_pr_ref


def test_parse_pr_ref_url():
    assert parse_pr_ref("https://github.com/Pulkit0111/ai_news_aggregator/pull/2") == (
        "Pulkit0111", "ai_news_aggregator", 2)


def test_parse_pr_ref_bare_number():
    assert parse_pr_ref("#2") == (None, None, 2)
    assert parse_pr_ref("2") == (None, None, 2)


def test_parse_pr_ref_none():
    assert parse_pr_ref("fix the routing bug") == (None, None, None)


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


# --- Fix: stop scraping arbitrary "word/word" prose as a repo (the docs/auth bug) ---

def test_prose_phrase_not_treated_as_repo_when_allowlist_set(monkeypatch):
    import bott.agents.build_fix.refs as refs
    monkeypatch.setattr(refs, "allowed_post_repos", lambda: {"pulkit0111/moodflix"})
    # "docs/auth" is an English phrase, not a repo — it must NOT become owner/repo.
    r = refs.parse_build_target("Fix the admin sync docs/auth mismatch")
    assert r.owner is None and r.repo is None


def test_prose_prefers_allowlisted_repo_over_phrase(monkeypatch):
    import bott.agents.build_fix.refs as refs
    monkeypatch.setattr(refs, "allowed_post_repos", lambda: {"pulkit0111/moodflix"})
    r = refs.parse_build_target("Fix the docs/auth mismatch in pulkit0111/moodflix")
    assert r.owner == "pulkit0111" and r.repo == "moodflix"


def test_prose_legacy_first_token_when_no_allowlist(monkeypatch):
    import bott.agents.build_fix.refs as refs
    monkeypatch.setattr(refs, "allowed_post_repos", lambda: set())
    r = refs.parse_build_target("open a PR on Pulkit0111/bott-pr-review-harness")
    assert r.owner == "Pulkit0111" and r.repo == "bott-pr-review-harness"
