import json

from bott.agents.triage import triage

_ISSUE = {"id": "12345", "shortId": "FOO-1", "title": "KeyError in checkout",
          "level": "error", "permalink": "https://sentry.io/o/i/12345", "count": "9"}
_EVENTS = [{"eventID": "e1", "message": "KeyError: 'sku'", "environment": "prod"}]


def _job(**over):
    args = {"sentry_issue_id": "12345", "owner": "axelerant", "name": "foo",
            "channel": "C1", "thread_ts": "t1", "user_id": "alice@x.com"}
    args.update(over)
    return args


def test_run_triage_job_creates_approval_and_posts(monkeypatch):
    monkeypatch.setattr(triage, "allowed_post_repos", lambda: {"axelerant/foo"})
    posts, approvals = [], []
    out = triage.run_triage_job(
        _job(),
        post=lambda ch, ts, blocks, fb: posts.append((ch, ts, blocks, fb)),
        create_approval=lambda **kw: approvals.append(kw) or 77,
        fetch=lambda sid: (_ISSUE, _EVENTS),
        diagnose=lambda issue, events: ("Root cause: missing sku key.", "Add a guard for missing 'sku'."),
    )
    assert out["status"] == "awaiting_approval" and out["approval_id"] == 77
    assert approvals and approvals[0]["action"] == "triage:implement"
    payload = json.loads(approvals[0]["payload"])
    assert payload == {"owner": "axelerant", "name": "foo",
                       "plan_text": "Add a guard for missing 'sku'.",
                       "channel": "C1", "thread_ts": "t1"}
    assert posts and posts[0][0] == "C1"


def test_run_triage_job_refuses_when_not_allowlisted(monkeypatch):
    monkeypatch.setattr(triage, "allowed_post_repos", lambda: set())  # empty allowlist
    posts, approvals = [], []
    out = triage.run_triage_job(
        _job(),
        post=lambda ch, ts, blocks, fb: posts.append((ch, ts, blocks, fb)),
        create_approval=lambda **kw: approvals.append(kw) or 1,
        fetch=lambda sid: (_ISSUE, _EVENTS),
        diagnose=lambda issue, events: ("d", "b"),
    )
    assert out["status"] == "refused_not_allowlisted"
    assert not approvals  # INVARIANT: no approval created for a non-allowlisted repo
    assert posts  # a refusal was posted
