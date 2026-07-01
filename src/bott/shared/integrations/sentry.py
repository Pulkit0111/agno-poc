"""Read-only Sentry REST client (org-credential, Bearer auth) — mirrors JiraClient.
Pure normalizers tolerate missing keys; _get is a thin httpx wrapper."""

from __future__ import annotations

from typing import Any

import httpx


def _norm_issue(i: dict) -> dict:
    i = i or {}
    return {
        "id": i.get("id", ""),
        "shortId": i.get("shortId", ""),
        "title": i.get("title") or i.get("culprit") or "",
        "culprit": i.get("culprit", ""),
        "level": i.get("level", ""),
        "status": i.get("status", ""),
        "count": i.get("count", ""),
        "userCount": i.get("userCount", ""),
        "permalink": i.get("permalink", ""),
        "lastSeen": i.get("lastSeen", ""),
        "assignedTo": (i.get("assignedTo") or {}).get("name", "") if isinstance(i.get("assignedTo"), dict) else "",
    }


def _norm_event(e: dict) -> dict:
    e = e or {}
    return {
        "eventID": e.get("eventID") or e.get("id", ""),
        "message": e.get("message") or e.get("title", ""),
        "dateCreated": e.get("dateCreated", ""),
        "release": (e.get("release") or {}).get("version", "") if isinstance(e.get("release"), dict) else (e.get("release") or ""),
        "environment": e.get("environment", ""),
    }


class SentryClient:
    def __init__(self, base_url: str, org_slug: str, api_token: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.org = org_slug
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = httpx.get(self.base_url + path, headers=self._headers,
                      params=params, timeout=self._timeout)
        r.raise_for_status()
        return r.json()

    def list_issues(self, query: str = "is:unresolved", limit: int = 20) -> list[dict]:
        raw = self._get(f"/api/0/organizations/{self.org}/issues/",
                        {"query": query, "limit": limit})
        return [_norm_issue(i) for i in (raw or [])]

    def get_issue(self, issue_id: str) -> dict:
        return _norm_issue(self._get(f"/api/0/organizations/{self.org}/issues/{issue_id}/"))

    def issue_events(self, issue_id: str, limit: int = 5) -> list[dict]:
        raw = self._get(f"/api/0/organizations/{self.org}/issues/{issue_id}/events/",
                        {"per_page": limit})
        return [_norm_event(e) for e in (raw or [])][:limit]
