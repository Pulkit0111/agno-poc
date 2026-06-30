import json

from bott.agents.build_fix import planner, rendering
from bott.agents.build_fix.core.models import ImplementPlan


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
