"""App Home sprint-report scheduler: cron weekday, modal, board options, sprint-end
lookup, schedule creation, and submit handling."""

from __future__ import annotations

from agno.db.sqlite import SqliteDb

from bott.interfaces.slack_home import blocks, router, service
from bott.interfaces.slack_home.cron import (
    cron_to_friendly,
    to_cron_weekday,
    weekday_to_cron_dow,
)
from bott.skills.sprint_report import tool


# ---- cron weekday ---------------------------------------------------------------
def test_weekday_cron_and_friendly():
    assert weekday_to_cron_dow(4) == 5  # Python Friday(4) -> cron Friday(5)
    assert to_cron_weekday(5, "17:00") == "0 17 * * 5"
    assert cron_to_friendly("0 17 * * 5") == "Fridays 5:00 PM"
    assert cron_to_friendly("30 9 * * 2") == "Tuesdays 9:30 AM"


# ---- modal ----------------------------------------------------------------------
def test_sprint_modal_states():
    loading = blocks.build_sprint_modal([], loading=True)
    assert loading["callback_id"] == "create_sprint"
    assert "Loading" in str(loading)

    boards = [("PADI — PADI Digital Overhaul", "PADI"), ("ACME — Acme Portal", "ACME")]
    m = blocks.build_sprint_modal(boards, selected_key="PADI",
                                  sprint_end_label="Current sprint ends Fri, 26 Jun · ~2-week cadence")
    blob = str(m)
    assert "sprint_eng_selected" in blob  # section-accessory select (dispatches on change)
    assert "Current sprint ends Fri, 26 Jun" in blob
    # selected engagement is pre-set
    eng_block = next(b for b in m["blocks"] if b.get("block_id") == "engagement")
    assert eng_block["accessory"]["initial_option"]["value"] == "PADI"


# ---- board options + sprint end lookup (mocked Jira) ----------------------------
class _FakeJira:
    def list_boards(self):
        return [{"id": 10, "name": "PADI board", "type": "scrum", "project_key": "PADI",
                 "project_name": "PADI Digital Overhaul"},
                {"id": 20, "name": "Acme", "type": "scrum", "project_key": "ACME",
                 "project_name": "Acme Portal"}]

    def find_board(self, q):
        return next((b for b in self.list_boards() if b["project_key"].lower() == q.lower()), None)

    def active_sprint(self, board_id):
        return {"id": 901, "name": "PADI Sprint 2", "state": "active",
                "start": "2026-06-15T00:00:00.000Z", "end": "2026-06-26T00:00:00.000Z"}

    def latest_closed_sprint(self, board_id):
        return None


def test_board_options(monkeypatch):
    from bott.interfaces.slack_home import engagements
    from bott.shared import config
    monkeypatch.setattr(config, "jira_configured", lambda: True)
    monkeypatch.setattr(tool, "_jira", lambda: _FakeJira())
    opts = engagements.sprint_board_options()
    assert ("ACME — Acme Portal", "ACME") in opts and ("PADI — PADI Digital Overhaul", "PADI") in opts
    assert opts[0][1] == "ACME"  # sorted by project name


def test_board_options_reason_distinguishes_causes(monkeypatch):
    """The empty state must say WHY (not the misleading 'no boards found')."""
    from bott.interfaces.slack_home import engagements
    from bott.shared import config

    # 1) not configured
    monkeypatch.setattr(config, "jira_configured", lambda: False)
    opts, reason = engagements.sprint_board_options_with_reason()
    assert opts == [] and "configured" in reason.lower()

    # 2) configured but the Jira call errors
    monkeypatch.setattr(config, "jira_configured", lambda: True)

    class Boom:
        def list_boards(self):
            raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(tool, "_jira", lambda: Boom())
    opts, reason = engagements.sprint_board_options_with_reason()
    assert opts == [] and "couldn't reach jira" in reason.lower()

    # 3) configured, reachable, but zero boards
    class Empty:
        def list_boards(self):
            return []

    monkeypatch.setattr(tool, "_jira", lambda: Empty())
    opts, reason = engagements.sprint_board_options_with_reason()
    assert opts == [] and "no scrum boards" in reason.lower()

    # 4) configured with boards -> no reason
    monkeypatch.setattr(tool, "_jira", lambda: _FakeJira())
    opts, reason = engagements.sprint_board_options_with_reason()
    assert opts and reason is None


def test_sprint_end_info(monkeypatch):
    monkeypatch.setattr(tool, "_jira", lambda: _FakeJira())
    info = service.sprint_end_info("PADI")
    assert info["cron_dow"] == 5  # 26 Jun 2026 is a Friday
    assert "Current sprint ends Fri, 26 Jun" in info["label"]
    assert "2-week" in info["label"]


def test_create_sprint_schedule_pins_end_weekday(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_jira", lambda: _FakeJira())
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    sch = service.create_sprint_report_schedule(db, "PADI", "C123", "17:00")
    assert getattr(sch, "cron_expr", "") == "0 17 * * 5"  # Friday, the sprint end weekday
    assert getattr(sch, "name", "") == "sprint-report:PADI"


# ---- submit handler -------------------------------------------------------------
def test_submit_sprint_reads_accessory_value(monkeypatch):
    captured = {}
    monkeypatch.setattr(service, "create_sprint_report_schedule",
                        lambda db, key, channel, time_str: captured.update(
                            {"key": key, "channel": channel, "time": time_str}))
    values = {
        "engagement": {"sprint_eng_selected": {"selected_option": {"value": "PADI"}}},
        "channel": {"v": {"selected_channel": "C123"}},
        "time": {"v": {"selected_time": "16:30"}},
    }
    router._submit_sprint(None, values)
    assert captured == {"key": "PADI", "channel": "C123", "time": "16:30"}
