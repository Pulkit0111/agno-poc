"""Jira Cloud client — just enough Agile REST API to build a sprint report.

Auth is HTTP basic (account email + API token), the standard Jira Cloud scheme. The
normalization functions (``normalize_sprint`` / ``normalize_issue``) are pure so they
can be unit-tested against fixture JSON with no network — HTTP lives only in the
``JiraClient`` methods.

API surface used (``/rest/agile/1.0``):
  - board/{id}/sprint?state=closed|future  -> sprints on the board
  - sprint/{id}/issue                       -> issues in a sprint
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.integrations.jira")

_AGILE = "/rest/agile/1.0"
# Issue fields we pull (keep narrow — sprints can hold a lot of issues).
_ISSUE_FIELDS = "summary,status,issuetype,labels"

# Heuristics for the "Sprint N+1 priorities" cards: a story is a spike / POC if its
# issue type or summary says so (Jira teams encode these inconsistently).
_SPIKE_HINT = ("spike",)
_POC_HINT = ("poc", "proof of concept", "proof-of-concept")


def _f(issue: dict, name: str, default: Any = None) -> Any:
    return (issue.get("fields") or {}).get(name, default)


# Field names Jira uses for the story-points estimate (varies by instance/template).
_SP_FIELD_NAMES = ("story points", "story point estimate")


def normalize_board(raw: dict) -> dict:
    """Flatten a raw Agile board to the engagement-identifying fields."""
    loc = raw.get("location") or {}
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "type": raw.get("type") or "",
        "project_key": (loc.get("projectKey") or loc.get("projectName") or "").strip(),
        "project_name": (loc.get("projectName") or raw.get("name") or "").strip(),
    }


def normalize_sprint(raw: dict) -> dict:
    """Flatten a raw Agile sprint object to the fields we render."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "state": (raw.get("state") or "").lower(),
        "start": raw.get("startDate"),
        "end": raw.get("endDate") or raw.get("completeDate"),
        "goal": raw.get("goal") or "",
    }


def _classify(summary: str, issue_type: str) -> Optional[str]:
    """'spike' | 'poc' | None — the small tag shown on a priority card."""
    blob = f"{issue_type} {summary}".lower()
    if any(h in blob for h in _SPIKE_HINT):
        return "spike"
    if any(h in blob for h in _POC_HINT):
        return "poc"
    return None


def normalize_issue(raw: dict, story_points_field: str | None) -> dict:
    """Flatten a raw issue to a render-ready dict. Story points come from an
    instance-specific custom field; absent/None -> 0.0 (and the report notes it)."""
    status = _f(raw, "status") or {}
    category = ((status.get("statusCategory") or {}).get("key") or "").lower()
    issue_type = (_f(raw, "issuetype") or {}).get("name") or ""
    summary = _f(raw, "summary") or ""
    points_raw = _f(raw, story_points_field) if story_points_field else None
    try:
        points = float(points_raw) if points_raw is not None else 0.0
    except (TypeError, ValueError):
        points = 0.0
    return {
        "key": raw.get("key") or "",
        "summary": summary,
        "status": status.get("name") or "",
        # Jira status categories: "new" | "indeterminate" (in progress) | "done".
        "status_category": category,
        "is_done": category == "done",
        "issue_type": issue_type,
        "points": points,
        "has_points": points_raw is not None,
        "labels": _f(raw, "labels") or [],
        "tag": _classify(summary, issue_type),
    }


class JiraClient:
    """Minimal Jira Cloud Agile API client (basic auth)."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        story_points_field: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (email, api_token)
        self.story_points_field = story_points_field
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        r = httpx.get(
            url, params=params, auth=self._auth, timeout=self.timeout,
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        return r.json() or {}

    # ---- discovery: boards + the site-wide story-points field --------------------
    def list_boards(self) -> list[dict]:
        """Every scrum/board the account can see (one per engagement), normalized."""
        out: list[dict] = []
        start = 0
        while True:
            page = self._get("/rest/agile/1.0/board", {"startAt": start, "maxResults": 50})
            vals = page.get("values") or []
            out.extend(vals)
            if page.get("isLast", True) or not vals:
                break
            start += len(vals)
        return [normalize_board(b) for b in out]

    @staticmethod
    def _prefer_scrum(boards: list[dict]) -> dict:
        """Among boards for one project, pick the Scrum board (only Scrum boards have
        sprints); fall back to the lowest-id board if none are Scrum."""
        scrum = [b for b in boards if b.get("type") == "scrum"]
        return min(scrum or boards, key=lambda b: b.get("id") or 0)

    def find_board(self, query: str) -> Optional[dict]:
        """Resolve an engagement to its board. Fast path: a project-key-scoped query (one
        request, a few boards) — avoids listing all ~hundreds of boards. Falls back to a
        fuzzy name match across all boards only when the key doesn't resolve. When a project
        has several boards, the Scrum board wins (it's the one with sprints)."""
        q = (query or "").strip()
        ql = q.lower()
        # Fast path: filter boards to this project key directly.
        try:
            page = self._get("/rest/agile/1.0/board", {"projectKeyOrId": q, "maxResults": 50})
            scoped = [normalize_board(b) for b in (page.get("values") or [])]
        except httpx.HTTPStatusError:
            scoped = []  # not a valid project key (400) — fall through to name search
        key_matches = [b for b in scoped if b["project_key"].lower() == ql]
        if key_matches:
            return self._prefer_scrum(key_matches)
        # Fallback: fuzzy name match across all boards (slower, only when key didn't resolve).
        boards = self.list_boards()
        name_matches = [b for b in boards if ql and (ql in b["name"].lower() or ql in b["project_name"].lower())]
        return self._prefer_scrum(name_matches) if name_matches else None

    def detect_story_points_field(self) -> Optional[str]:
        """Find the story-points custom field id from Jira's field catalogue (site-wide)."""
        fields = self._get("/rest/api/3/field")
        items = fields if isinstance(fields, list) else (fields.get("values") or [])
        for f in items:
            if (f.get("name") or "").strip().lower() in _SP_FIELD_NAMES:
                return f.get("id") or f.get("key")
        return None

    def ensure_story_points_field(self) -> Optional[str]:
        """Use the configured/explicit field if set, else detect and cache it once."""
        if self.story_points_field:
            return self.story_points_field
        self.story_points_field = self.detect_story_points_field()
        return self.story_points_field

    def _sprints(self, board_id: int, state: str) -> list[dict]:
        """All sprints on a board in a given state (paginated). A Kanban board (or any board
        that doesn't support sprints) returns HTTP 400 here — treated as 'no sprints'."""
        out: list[dict] = []
        start = 0
        while True:
            try:
                page = self._get(
                    f"{_AGILE}/board/{board_id}/sprint",
                    {"state": state, "startAt": start, "maxResults": 50},
                )
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code == 400:
                    return []  # board doesn't support sprints (e.g. Kanban)
                raise
            out.extend(page.get("values") or [])
            if page.get("isLast", True) or not page.get("values"):
                break
            start += len(page["values"])
        return [normalize_sprint(s) for s in out]

    def latest_closed_sprint(self, board_id: int) -> Optional[dict]:
        """The most recently completed sprint (by id — Jira ids are monotonic)."""
        closed = self._sprints(board_id, "closed")
        if not closed:
            return None
        return max(closed, key=lambda s: s.get("id") or 0)

    def active_sprint(self, board_id: int) -> Optional[dict]:
        """The currently-running sprint (its end date is the upcoming sprint end)."""
        active = self._sprints(board_id, "active")
        if not active:
            return None
        return min(active, key=lambda s: s.get("id") or 0)

    def next_future_sprint(self, board_id: int) -> Optional[dict]:
        """The soonest not-yet-started sprint (lowest id among future)."""
        future = self._sprints(board_id, "future")
        if not future:
            return None
        return min(future, key=lambda s: s.get("id") or 0)

    def get_sprint(self, sprint_id: int) -> dict:
        return normalize_sprint(self._get(f"{_AGILE}/sprint/{sprint_id}"))

    def sprint_issues(self, sprint_id: int) -> list[dict]:
        """All issues in a sprint, normalized (paginated)."""
        out: list[dict] = []
        start = 0
        while True:
            page = self._get(
                f"{_AGILE}/sprint/{sprint_id}/issue",
                {
                    "startAt": start,
                    "maxResults": 100,
                    "fields": self._fields(),
                },
            )
            issues = page.get("issues") or []
            out.extend(issues)
            total = page.get("total", 0)
            start += len(issues)
            if not issues or start >= total:
                break
        return [normalize_issue(i, self.story_points_field) for i in out]

    def _fields(self) -> str:
        if self.story_points_field:
            return f"{_ISSUE_FIELDS},{self.story_points_field}"
        return _ISSUE_FIELDS
