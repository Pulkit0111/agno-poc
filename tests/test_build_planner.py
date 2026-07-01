import json

from bott.agents.build_fix import planner, rendering
from bott.agents.build_fix.core.models import ImplementPlan
from bott.agents.build_fix.planning import draft_plan_text


def test_plan_blocks_have_approve_dismiss_buttons():
    blocks, fallback = rendering.plan_blocks(
        ImplementPlan(summary="add endpoint", steps=["a", "b"]), approval_id=7)
    action_ids = [e.get("action_id") for b in blocks if b.get("type") == "actions"
                  for e in b.get("elements", [])]
    assert "approval_approve" in action_ids and "approval_dismiss" in action_ids
    values = [e.get("value") for b in blocks if b.get("type") == "actions"
              for e in b.get("elements", [])]
    assert "7" in values


def test_run_plan_job_refuses_repo_not_in_allowlist(monkeypatch):
    monkeypatch.setattr(planner, "allowed_post_repos", lambda: {"ok/repo"})
    posted = []
    created = []  # sentinel: records any create_approval call
    out = planner.run_plan_job(
        {"owner": "bad", "name": "repo", "plan_text": "x", "channel": "C", "thread_ts": "t"},
        post=lambda *a, **k: posted.append(a),
        create_approval=lambda **k: created.append(k) or 1)
    assert out["status"] == "refused_not_allowlisted"
    assert out["approval_id"] is None
    assert not created  # the write-gate: NO approval row created for a non-allowlisted repo
    assert posted  # a refusal message was posted


def test_run_plan_job_creates_approval_with_payload(monkeypatch):
    monkeypatch.setattr(planner, "allowed_post_repos", lambda: {"ok/repo"})
    captured = {}
    def fake_create(**k):
        captured.update(k)
        return 42
    out = planner.run_plan_job(
        {"owner": "ok", "name": "repo", "plan_text": "add x", "channel": "C", "thread_ts": "t",
         "user_id": "alice@x.com"},
        post=lambda *a, **k: None, create_approval=fake_create)
    assert out["approval_id"] == 42
    assert captured["action"] == "build:implement"
    payload = json.loads(captured["payload"])
    assert payload["owner"] == "ok" and payload["name"] == "repo" and payload["plan_text"] == "add x"


# --- Fix 2 & 3 integration tests: real enqueue-path args (key=repo, not name) ---

def _make_plan_args(owner, repo, text="open a PR"):
    """Reproduce the args dict that start_build/queue.enqueue produces.

    Note: member.py enqueues 'repo' not 'name'; plan_text is added upstream.
    """
    plan_text = draft_plan_text({"kind": "request", "owner": owner, "repo": repo, "text": text})
    return {
        "kind": "request",
        "owner": owner,
        "repo": repo,        # <-- real key from enqueue (was causing KeyError: 'name')
        "issue": None,
        "jira_key": None,
        "text": text,
        "channel": "C123",
        "thread_ts": "ts1",
        "plan_text": plan_text,
    }


def test_integration_repo_key_no_keyerror_creates_approval(monkeypatch):
    """Fix 2: run_plan_job must NOT KeyError when args carry 'repo' instead of 'name'."""
    monkeypatch.setattr(planner, "allowed_post_repos",
                        lambda: {"pulkit0111/bott-pr-review-harness"})
    captured = {}
    def fake_create(**k):
        captured.update(k)
        return 99

    args = _make_plan_args("Pulkit0111", "bott-pr-review-harness",
                           "open a PR on Pulkit0111/bott-pr-review-harness")
    # This MUST NOT raise KeyError: 'name'
    out = planner.run_plan_job(args, post=lambda *a, **k: None, create_approval=fake_create)

    assert out["status"] == "awaiting_approval"
    assert out["approval_id"] == 99
    payload = json.loads(captured["payload"])
    assert payload["name"] == "bott-pr-review-harness"
    assert captured["action"] == "build:implement"


def test_integration_unresolved_repo_posts_message_no_approval(monkeypatch):
    """Fix 3: when owner/name are both None, post a helpful message and return no_repo."""
    monkeypatch.setattr(planner, "allowed_post_repos", lambda: {"ok/repo"})
    posted = []
    created = []

    # Args with no owner/repo (unresolved fallback) — as produced by a pure-prose parse
    args = {
        "kind": "request",
        "owner": None,
        "repo": None,
        "issue": None,
        "jira_key": None,
        "text": "please build something",
        "channel": "C123",
        "thread_ts": "ts1",
        "plan_text": "please build something",
    }
    out = planner.run_plan_job(args,
                               post=lambda *a, **k: posted.append(a),
                               create_approval=lambda **k: created.append(k) or 1)

    assert out["status"] == "no_repo"
    assert out["approval_id"] is None
    assert not created          # no approval row created
    assert posted               # user got a message asking which repo
    # confirm the message text is helpful
    msg_text = posted[0][2][0]["text"]["text"]
    assert "owner/repo" in msg_text or "repo" in msg_text.lower()
