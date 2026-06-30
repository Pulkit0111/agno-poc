import pytest

from bott.shared import approvals, db


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "a.db"))
    db.get_engine(fresh=True)
    approvals.init_approvals()
    yield


def test_pending_then_approved(store):
    aid = approvals.create_request("alice@x.com", "open_pr", "Open PR #12")
    assert approvals.status(aid) == "pending"
    approvals.decide(aid, approved=True, decided_by="alice@x.com")
    assert approvals.status(aid) == "approved"


def test_dismissed(store):
    aid = approvals.create_request("u", "send_email", "Email client")
    approvals.decide(aid, approved=False, decided_by="u")
    assert approvals.status(aid) == "dismissed"


def test_wait_returns_immediately_when_decided(store):
    aid = approvals.create_request("u", "x", "y")
    approvals.decide(aid, approved=True, decided_by="u")
    assert approvals.wait_for_decision(aid, timeout=1.0, poll=0.05) == "approved"


def test_wait_times_out_returns_pending(store):
    aid = approvals.create_request("u", "x", "y")
    assert approvals.wait_for_decision(aid, timeout=0.1, poll=0.05) == "pending"


def test_create_request_stores_payload(store):
    aid = approvals.create_request("u", "build:implement", "Open PR", payload='{"owner":"o"}')
    row = approvals.get_request(aid)
    assert row is not None
    assert row["action"] == "build:implement"
    assert row["payload"] == '{"owner":"o"}'
    assert row["status"] == "pending"


def test_get_request_missing_returns_none(store):
    assert approvals.get_request(999999) is None
