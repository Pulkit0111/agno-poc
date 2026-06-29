from types import SimpleNamespace

import bott.skills.scheduling as scheduling


class _FakeSched:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.cron_expr = "0 9 * * *"


class _FakeMgr:
    def __init__(self, db):
        pass
    def list(self):
        return [_FakeSched("s1", "concierge:alice@x.com:standup"),
                _FakeSched("s2", "concierge:bob@x.com:report")]
    def delete(self, sid):
        _FakeMgr.deleted = sid


def test_create_embeds_user_id(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduling, "create_recurring_task", lambda db, **k: calls.append(k))
    ctx = SimpleNamespace(user_id="alice@x.com")
    out = scheduling._create_schedule_impl(object(), ctx, "0 9 * * *", "Post standup")
    assert calls and calls[0]["user_id"] == "alice@x.com" and calls[0]["cron"] == "0 9 * * *"
    assert "Scheduled" in out


def test_create_requires_user():
    ctx = SimpleNamespace(user_id=None)
    out = scheduling._create_schedule_impl(object(), ctx, "0 9 * * *", "x")
    assert "couldn't tell who you are" in out.lower()


def test_list_only_mine(monkeypatch):
    monkeypatch.setattr(scheduling, "ScheduleManager", _FakeMgr)
    ctx = SimpleNamespace(user_id="alice@x.com")
    out = scheduling._list_my_schedules_impl(object(), ctx)
    assert "s1" in out and "s2" not in out


def test_remove_refuses_cross_user(monkeypatch):
    monkeypatch.setattr(scheduling, "ScheduleManager", _FakeMgr)
    ctx = SimpleNamespace(user_id="alice@x.com")
    out = scheduling._remove_schedule_impl(object(), ctx, "s2")  # bob's
    assert "isn't one of yours" in out
