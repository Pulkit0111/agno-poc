"""The action policy — determinism lives on WHAT'S ALLOWED, never on what's possible.

Reads are free; safe writes are allowed (logged); world-changing/outward writes gate on
human approval; destructive/identity-risk actions are denied with a reason.
"""

from __future__ import annotations

import pytest

from bott.shared.action_policy import Decision, classify

# ---- Slack -----------------------------------------------------------------

def test_slack_reads_allowed():
    for m in ("conversations.history", "conversations.info", "users.info",
              "reactions.get", "team.info", "auth.test", "chat.scheduledMessages.list"):
        assert classify("slack", m).verdict == "allow", m


def test_slack_safe_writes_allowed():
    for m in ("chat.postMessage", "chat.scheduleMessage", "chat.update",
              "reactions.add", "reactions.remove", "pins.add", "pins.remove"):
        assert classify("slack", m).verdict == "allow", m


def test_slack_risky_writes_gate():
    for m in ("chat.delete", "conversations.invite", "conversations.create",
              "conversations.archive", "conversations.setTopic"):
        d = classify("slack", m)
        assert d.verdict == "gate", m


def test_slack_admin_denied():
    d = classify("slack", "admin.users.remove")
    assert d.verdict == "deny" and d.reason


def test_slack_unknown_method_denied():
    assert classify("slack", "made.up.method").verdict == "deny"


# ---- GitHub ----------------------------------------------------------------

def test_github_get_always_allowed():
    assert classify("github", "GET", path="/repos/o/r/pulls/1").verdict == "allow"
    assert classify("github", "GET", path="/search/issues").verdict == "allow"


def test_github_issue_comment_allowed_on_allowlisted_repo(monkeypatch):
    monkeypatch.setenv("ALLOWED_POST_REPOS", "o/r")
    d = classify("github", "POST", path="/repos/o/r/issues/5/comments")
    assert d.verdict == "allow"


def test_github_write_on_non_allowlisted_repo_denied(monkeypatch):
    monkeypatch.setenv("ALLOWED_POST_REPOS", "o/r")
    d = classify("github", "POST", path="/repos/other/repo/issues/5/comments")
    assert d.verdict == "deny" and "allow" in d.reason.lower()


def test_github_merge_gates(monkeypatch):
    monkeypatch.setenv("ALLOWED_POST_REPOS", "o/r")
    assert classify("github", "PUT", path="/repos/o/r/pulls/3/merge").verdict == "gate"


def test_github_write_denied_when_allowlist_unset(monkeypatch):
    """Fail closed: a blank/unset ALLOWED_POST_REPOS must deny every repo, not allow every
    repo — a prior bug let an empty allowlist skip the restriction and auto-approve safe
    writes (issue comments, labels, etc.) on ANY repo the GitHub App can reach."""
    monkeypatch.delenv("ALLOWED_POST_REPOS", raising=False)
    d = classify("github", "POST", path="/repos/o/r/issues/5/comments")
    assert d.verdict == "deny" and "allow" in d.reason.lower()


def test_github_contents_and_delete_denied(monkeypatch):
    monkeypatch.setenv("ALLOWED_POST_REPOS", "o/r")
    # Code changes belong to the build pipeline (plan→approve→implement), not raw API writes.
    assert classify("github", "PUT", path="/repos/o/r/contents/x.py").verdict == "deny"
    assert classify("github", "DELETE", path="/repos/o/r").verdict == "deny"


# ---- Atlassian ---------------------------------------------------------------

def test_atlassian_get_allowed_and_writes_gate():
    assert classify("atlassian", "GET", path="/rest/api/3/issue/IRM-1").verdict == "allow"
    assert classify("atlassian", "POST", path="/rest/api/3/issue/IRM-1/comment").verdict == "gate"
    assert classify("atlassian", "DELETE", path="/rest/api/3/issue/IRM-1").verdict == "deny"


# ---- HTTP -------------------------------------------------------------------

def test_http_get_https_allowed():
    assert classify("http", "GET", url="https://api.example.com/data").verdict == "allow"


def test_http_non_get_denied():
    assert classify("http", "POST", url="https://api.example.com/data").verdict == "deny"


def test_http_private_hosts_denied():
    for url in ("https://localhost/x", "http://127.0.0.1/x", "https://10.0.0.5/x",
                "https://192.168.1.1/x", "https://169.254.1.1/x", "https://172.20.3.4/x"):
        assert classify("http", "GET", url=url).verdict == "deny", url


def test_decision_dataclass_shape():
    d = classify("slack", "chat.postMessage")
    assert isinstance(d, Decision) and d.verdict in ("allow", "gate", "deny")


# ---- Overrides ---------------------------------------------------------------
#
# classify() now checks policy_overrides.get_override() first, which reads through
# records.get_setting() — a real DB call. autouse=True so this isolated, freshly
# initialized DB applies to every test in this file (not just the two below that
# reference it as a parameter) — otherwise every other test here would run against
# whatever database the process resolves to by default, silently depending on
# ambient state (e.g. a real override sitting in a developer's dev DB).

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    import os

    from bott.shared import db
    from bott.shared.schema import init_schema
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "agentos.db"))
    db.get_engine(fresh=True)
    init_schema()


def test_classify_override_takes_precedence(_tmp_db):
    from bott.shared import action_policy, policy_overrides
    # Known default-allow case (same as test_github_get_always_allowed above) — override it
    # to deny and confirm the override wins over the hardcoded "GET is always allowed" rule.
    policy_overrides.set_override("github", "GET", "deny", "test override", "a@x.com")
    decision = action_policy.classify("github", "GET", path="/repos/o/r/pulls/1")
    assert decision.verdict == "deny"
    assert "override" in decision.reason


def test_classify_falls_through_when_no_override(_tmp_db):
    from bott.shared import action_policy
    # Same call, WITHOUT setting an override — must still allow, matching
    # test_github_get_always_allowed's existing assertion.
    decision = action_policy.classify("github", "GET", path="/repos/o/r/pulls/1")
    assert decision.verdict == "allow"
