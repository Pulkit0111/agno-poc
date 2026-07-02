"""Lightweight, read-only sprint snapshot used by the App Home 'Sprint report' quick action."""

from __future__ import annotations

from types import SimpleNamespace

import bott.skills.sprint_report.tool as t


class _FakeClient:
    def __init__(self, sprint):
        self._sprint = sprint

    def active_sprint(self, board_id):
        return self._sprint

    def latest_closed_sprint(self, board_id):
        return None

    def sprint_issues(self, sprint_id):
        return [
            {"is_done": True, "points": 3.0},
            {"is_done": False, "points": 2.0},
            {"is_done": True, "points": 0.0},
        ]


def test_sprint_snapshot_reports_counts(monkeypatch):
    eng = SimpleNamespace(
        client=_FakeClient({"id": 5, "name": "PADI Sprint 2", "state": "active"}),
        board_id=1, project_key="PADI",
    )
    monkeypatch.setattr(t, "_resolve_engagement", lambda q: eng)
    out = t.sprint_snapshot("PADI")
    assert "PADI" in out and "Sprint 2" in out
    assert "2/3" in out  # 2 of 3 issues done


def test_sprint_snapshot_no_board(monkeypatch):
    monkeypatch.setattr(t, "_resolve_engagement", lambda q: None)
    assert "couldn't find" in t.sprint_snapshot("Nope").lower()


def test_sprint_snapshot_no_sprint(monkeypatch):
    eng = SimpleNamespace(client=_FakeClient(None), board_id=1, project_key="PADI")
    monkeypatch.setattr(t, "_resolve_engagement", lambda q: eng)
    assert "no active or recent sprint" in t.sprint_snapshot("PADI").lower()
