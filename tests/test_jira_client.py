"""Jira normalization (pure) + client paging with a stubbed transport."""

from __future__ import annotations

from bott.shared.integrations.jira import JiraClient, normalize_issue, normalize_sprint

SP = "customfield_10016"


def _raw_issue(key, summary, cat, itype="Story", points=None, labels=None):
    fields = {"summary": summary, "status": {"name": cat.title(),
              "statusCategory": {"key": cat}}, "issuetype": {"name": itype},
              "labels": labels or []}
    if points is not None:
        fields[SP] = points
    return {"key": key, "fields": fields}


def test_normalize_issue_points_done_and_tags():
    done = normalize_issue(_raw_issue("P-1", "Build", "done", points=5), SP)
    assert done["is_done"] and done["points"] == 5.0 and done["has_points"]
    assert done["tag"] is None

    spike = normalize_issue(_raw_issue("P-2", "Research auth", "new", itype="Spike"), SP)
    assert spike["tag"] == "spike" and not spike["is_done"]

    poc = normalize_issue(_raw_issue("P-3", "POC for SSO", "indeterminate"), SP)
    assert poc["tag"] == "poc"

    nopts = normalize_issue(_raw_issue("P-4", "x", "done"), SP)
    assert nopts["points"] == 0.0 and nopts["has_points"] is False


def test_normalize_sprint():
    s = normalize_sprint({"id": 10, "name": "PADI Sprint 1", "state": "CLOSED",
                          "startDate": "2026-06-01", "endDate": "2026-06-12"})
    assert s["id"] == 10 and s["state"] == "closed" and s["name"] == "PADI Sprint 1"


def test_client_latest_closed_and_sprint_issues(monkeypatch):
    client = JiraClient("https://j", "e@x", "tok", story_points_field=SP)

    def fake_get(path, params=None):
        if "/board/55/sprint" in path and params.get("state") == "closed":
            return {"isLast": True, "values": [
                {"id": 1, "name": "Sprint 1", "state": "closed"},
                {"id": 3, "name": "Sprint 3", "state": "closed"}]}
        if "/sprint/3/issue" in path:
            return {"total": 2, "issues": [
                _raw_issue("P-1", "A", "done", points=5),
                _raw_issue("P-2", "B", "new", points=2)]}
        return {"isLast": True, "values": [], "issues": [], "total": 0}

    monkeypatch.setattr(client, "_get", fake_get)
    latest = client.latest_closed_sprint(55)
    assert latest["id"] == 3  # highest id wins
    issues = client.sprint_issues(3)
    assert len(issues) == 2 and issues[0]["points"] == 5.0


def test_find_board_by_key_then_name(monkeypatch):
    client = JiraClient("https://j", "e@x", "tok")
    boards = {"isLast": True, "values": [
        {"id": 10, "name": "PADI board", "type": "scrum",
         "location": {"projectKey": "PADI", "projectName": "PADI Digital Overhaul"}},
        {"id": 20, "name": "Acme Sprint Board", "type": "scrum",
         "location": {"projectKey": "ACME", "projectName": "Acme Portal"}},
    ]}
    monkeypatch.setattr(client, "_get", lambda path, params=None: boards)
    assert client.find_board("padi")["id"] == 10  # exact key, case-insensitive
    assert client.find_board("acme portal")["id"] == 20  # name substring
    assert client.find_board("nope") is None


def test_find_board_prefers_scrum_for_sprint_capable_project(monkeypatch):
    """A project can have several boards (Kanban + Scrum); only Scrum has sprints, so
    resolution must pick the Scrum one."""
    client = JiraClient("https://j", "e@x", "tok")
    boards = {"isLast": True, "values": [
        {"id": 2745, "name": "PADI board", "type": "kanban",
         "location": {"projectKey": "PADI", "projectName": "PADI Digital Overhaul"}},
        {"id": 3374, "name": "PADI- Dev", "type": "scrum",
         "location": {"projectKey": "PADI", "projectName": "PADI Digital Overhaul"}},
    ]}
    monkeypatch.setattr(client, "_get", lambda path, params=None: boards)
    assert client.find_board("PADI")["id"] == 3374  # the scrum board, not the first match


def test_sprints_tolerates_kanban_400(monkeypatch):
    """The sprint endpoint 400s for boards that don't support sprints (Kanban) — treat
    that as 'no sprints', not a hard error."""
    import httpx

    client = JiraClient("https://j", "e@x", "tok")

    def boom(path, params=None):
        req = httpx.Request("GET", "https://j" + path)
        resp = httpx.Response(400, request=req, text="board does not support sprints")
        raise httpx.HTTPStatusError("400", request=req, response=resp)

    monkeypatch.setattr(client, "_get", boom)
    assert client.latest_closed_sprint(583) is None  # degrades cleanly, no raise
    assert client.active_sprint(583) is None


def test_detect_story_points_field(monkeypatch):
    client = JiraClient("https://j", "e@x", "tok")
    fields = [{"id": "summary", "name": "Summary"},
              {"id": "customfield_10016", "name": "Story Points"}]
    monkeypatch.setattr(client, "_get", lambda path, params=None: fields)
    assert client.detect_story_points_field() == "customfield_10016"
    # ensure_* caches it on the client
    assert client.ensure_story_points_field() == "customfield_10016"
