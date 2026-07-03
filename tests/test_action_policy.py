"""The action policy — determinism lives on WHAT'S ALLOWED, never on what's possible.

Reads are free; safe writes are allowed (logged); world-changing/outward writes gate on
human approval; destructive/identity-risk actions are denied with a reason.
"""

from __future__ import annotations

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
