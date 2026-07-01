import json

from bott.interfaces.slack_home import router
from bott.shared import approvals, db


def _store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "d.db"))
    db.get_engine(fresh=True)
    approvals.init_approvals()


def test_dispatch_enqueues_implement_for_approved_triage(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    enq = []
    monkeypatch.setattr(router.queue, "enqueue",
                        lambda kind, payload, user_id, dedup_key=None: enq.append((kind, payload, dedup_key)) or 1)
    payload = json.dumps({"owner": "axelerant", "name": "foo", "plan_text": "fix it",
                          "channel": "C1", "thread_ts": "t1"})
    aid = approvals.create_request("alice@x.com", "triage:implement", "Fix foo", payload=payload)
    approvals.decide(aid, approved=True, decided_by="alice@x.com")
    router.dispatch_approved_build(aid)
    assert enq and enq[0][0] == "implement"
    assert enq[0][1]["owner"] == "axelerant" and enq[0][1]["plan_text"] == "fix it"


def test_dispatch_ignores_unapproved_triage(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    enq = []
    monkeypatch.setattr(router.queue, "enqueue", lambda *a, **k: enq.append(a) or 1)
    aid = approvals.create_request("u", "triage:implement", "x", payload="{}")
    router.dispatch_approved_build(aid)  # still pending
    assert not enq
