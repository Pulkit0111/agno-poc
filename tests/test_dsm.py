"""DSM standup: collection storage round-trip + submission rendering (no network)."""

from __future__ import annotations

import pytest

from bott.shared import db
from bott.shared.persistence import standup
from bott.skills import dsm


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    yield


def test_round_and_responses_round_trip(engine):
    standup.open_round("core", "2026-06-18", "C1", "111.1")
    assert standup.get_round("core", "2026-06-18") == {"channel": "C1", "thread_ts": "111.1"}
    standup.add_response("core", "2026-06-18", "U1", "did x", "do y", "blocked on infra")
    standup.add_response("core", "2026-06-18", "U2", "a", "b", "")
    rs = standup.responses("core", "2026-06-18")
    assert [r["user"] for r in rs] == ["U1", "U2"]
    # A different day is a different round.
    assert standup.responses("core", "2026-06-19") == []


def test_open_round_upserts_on_conflict(engine):
    """Re-opening the same team+date updates the thread root instead of erroring."""
    standup.open_round("core", "2026-06-18", "C1", "111.1")
    standup.open_round("core", "2026-06-18", "C2", "222.2")
    assert standup.get_round("core", "2026-06-18") == {"channel": "C2", "thread_ts": "222.2"}


def test_render_submissions_groups_blockers():
    out = dsm._render_submissions("core", [
        {"user": "U1", "yesterday": "x", "today": "y", "blockers": "infra creds"},
        {"user": "U2", "yesterday": "a", "today": "b", "blockers": ""},
    ])
    assert "<@U1>" in out and "<@U2>" in out
    assert "infra creds" in out
    assert "Blockers to discuss" in out


def test_render_submissions_empty():
    assert "No updates" in dsm._render_submissions("core", [])


def test_open_blocks_value_is_string():
    blocks = dsm.standup_open_blocks(None)
    val = blocks[1]["elements"][0]["value"]
    assert isinstance(val, str) and val != ""


def test_open_standup_guards_missing_team(monkeypatch):
    monkeypatch.setattr(dsm, "_client", lambda: object())  # truthy, won't be used
    out = dsm.open_standup("", "C1")
    assert "team" in out.lower()


# ---------------------------------------------------------------------------
# close_standup: auto-capture a follow-up action item per blocker-holder,
# deduped/idempotent per (team, date, user) — re-closing must not duplicate.
# ---------------------------------------------------------------------------

class _FakeSlackClient:
    """Enough of slack_sdk.WebClient's surface for close_standup's auto-capture:
    users_info (email resolution) + chat_postMessage (the pre-read post)."""

    def __init__(self, email_by_user: dict[str, str]):
        self._email_by_user = email_by_user
        self.posts: list[dict] = []

    def users_info(self, user):
        email = self._email_by_user.get(user)
        return {"user": {"profile": ({"email": email} if email else {})}}

    def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ts": "1.1"}


def test_close_standup_creates_action_item_per_blocker_holder(engine, monkeypatch):
    from bott.shared.persistence import action_items

    standup.add_response("core", dsm.today_key(), "U1", "did x", "do y", "blocked on infra creds")
    standup.add_response("core", dsm.today_key(), "U2", "a", "b", "")  # no blocker

    fake = _FakeSlackClient({"U1": "alice@x.com", "U2": "bob@x.com"})
    monkeypatch.setattr(dsm, "_client", lambda: fake)

    dsm.close_standup("core", "C1")

    alice_items = action_items.list_items("alice@x.com")
    assert len(alice_items) == 1
    assert alice_items[0]["source"] == "dsm"
    assert "blocked on infra creds" in alice_items[0]["text"]
    assert action_items.list_items("bob@x.com") == []


def test_close_standup_is_idempotent_on_reclose(engine, monkeypatch):
    from bott.shared.persistence import action_items

    standup.add_response("core", dsm.today_key(), "U1", "x", "y", "blocked on infra")
    fake = _FakeSlackClient({"U1": "alice@x.com"})
    monkeypatch.setattr(dsm, "_client", lambda: fake)

    dsm.close_standup("core", "C1")
    dsm.close_standup("core", "C1")

    assert len(action_items.list_items("alice@x.com")) == 1


def test_close_standup_skips_responder_with_unresolvable_email(engine, monkeypatch):
    from bott.shared.persistence import action_items

    standup.add_response("core", dsm.today_key(), "U1", "x", "y", "blocked on infra")
    fake = _FakeSlackClient({})  # no email on file for U1
    monkeypatch.setattr(dsm, "_client", lambda: fake)

    dsm.close_standup("core", "C1")

    # Must not fall back to storing the raw Slack id as user_id — the console keys on email.
    assert action_items.list_items("U1") == []


def test_close_standup_no_op_when_no_blockers(engine, monkeypatch):
    from bott.shared.persistence import action_items

    standup.add_response("core", dsm.today_key(), "U1", "x", "y", "")
    fake = _FakeSlackClient({"U1": "alice@x.com"})
    monkeypatch.setattr(dsm, "_client", lambda: fake)

    dsm.close_standup("core", "C1")

    assert action_items.list_items("alice@x.com") == []
