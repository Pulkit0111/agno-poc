"""Minimal GitHub REST client over httpx (port of the bits of git-provider used
by the review pipeline). Phase 1 needs reads only; post_review is used in phase 3.

Auth: optional token (phase 1, to dodge the 60/hr unauthenticated limit). Never
hardcode secrets — token comes from config.github_token().
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from bott.shared.observability.logging_setup import get_logger

from ..core.types import CiCheck, CiStatus

API = "https://api.github.com"
log = get_logger("review.github")
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_TRIES = 3


@dataclass
class PrMeta:
    owner: str
    name: str
    number: int
    url: str
    title: str
    body: str
    author_login: Optional[str]
    state: str
    draft: bool
    head_sha: str
    base_sha: str
    head_ref: str
    base_ref: str
    additions: int
    deletions: int
    changed_files: int


@dataclass
class Comment:
    body: str
    author: Optional[str]
    path: Optional[str] = None
    line: Optional[int] = None


@dataclass
class PrComments:
    issue_comments: list[Comment] = field(default_factory=list)
    review_comments: list[Comment] = field(default_factory=list)


_FAIL_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "stale"}
_PASS_CONCLUSIONS = {"success", "neutral", "skipped"}


class GitHubClient:
    def __init__(self, token: Optional[str] = None, timeout: float = 30.0):
        self._token = token
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "bott-poc-review",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(base_url=API, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- low level ---
    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        """HTTP with retry on transient errors (429 / 5xx / 403-rate-limit)."""
        last: httpx.Response | None = None
        for attempt in range(_MAX_TRIES):
            r = self._http.request(method, path, **kwargs)
            transient = r.status_code in _RETRY_STATUS or (
                r.status_code == 403 and "rate limit" in r.text.lower()
            )
            if transient and attempt < _MAX_TRIES - 1:
                wait = 2 ** attempt
                log.warning("GitHub %s %s -> %s; retrying in %ss", method, path, r.status_code, wait)
                time.sleep(wait)
                last = r
                continue
            return r
        return last  # type: ignore[return-value]

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self._send("GET", path, params=params)
        r.raise_for_status()
        return r.json()

    def _paginate(self, path: str, params: dict | None = None) -> list[Any]:
        out: list[Any] = []
        page = 1
        params = dict(params or {})
        params.setdefault("per_page", 100)
        while True:
            params["page"] = page
            r = self._send("GET", path, params=params)
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            if len(batch) < params["per_page"]:
                break
            page += 1
        return out

    # --- PR reads ---
    def get_pr(self, owner: str, name: str, number: int) -> PrMeta:
        d = self._get(f"/repos/{owner}/{name}/pulls/{number}")
        return PrMeta(
            owner=owner,
            name=name,
            number=d["number"],
            url=d["html_url"],
            title=d.get("title") or "",
            body=d.get("body") or "",
            author_login=(d.get("user") or {}).get("login"),
            state=d.get("state", "open"),
            draft=bool(d.get("draft", False)),
            head_sha=d["head"]["sha"],
            base_sha=d["base"]["sha"],
            head_ref=d["head"]["ref"],
            base_ref=d["base"]["ref"],
            additions=d.get("additions", 0),
            deletions=d.get("deletions", 0),
            changed_files=d.get("changed_files", 0),
        )

    def list_files(self, owner: str, name: str, number: int) -> list[dict]:
        """Returns raw file dicts: {filename, status, additions, deletions, patch?}."""
        return self._paginate(f"/repos/{owner}/{name}/pulls/{number}/files")

    def get_ci_status(self, owner: str, name: str, sha: str) -> CiStatus:
        failing: list[CiCheck] = []
        pending: list[CiCheck] = []
        passing: list[CiCheck] = []

        # Legacy combined statuses (e.g. external CI via the Status API).
        try:
            combined = self._get(f"/repos/{owner}/{name}/commits/{sha}/status")
            for s in combined.get("statuses", []):
                name_ = s.get("context", "status")
                state = s.get("state")
                if state == "success":
                    passing.append(CiCheck(name_))
                elif state in ("failure", "error"):
                    failing.append(CiCheck(name_))
                else:
                    pending.append(CiCheck(name_))
        except httpx.HTTPError:
            pass

        # Check runs (GitHub Actions / Checks API).
        try:
            checks = self._get(f"/repos/{owner}/{name}/commits/{sha}/check-runs")
            for c in checks.get("check_runs", []):
                name_ = c.get("name", "check")
                if c.get("status") != "completed":
                    pending.append(CiCheck(name_))
                elif (c.get("conclusion") or "") in _FAIL_CONCLUSIONS:
                    failing.append(CiCheck(name_))
                elif (c.get("conclusion") or "") in _PASS_CONCLUSIONS:
                    passing.append(CiCheck(name_))
                else:
                    pending.append(CiCheck(name_))
        except httpx.HTTPError:
            pass

        if failing:
            overall = "fail"
        elif pending:
            overall = "pending"
        elif passing:
            overall = "pass"
        else:
            overall = "none"
        return CiStatus(overall=overall, failing=failing, pending=pending, passing=passing)

    def list_all_comments(self, owner: str, name: str, number: int) -> PrComments:
        out = PrComments()
        try:
            for c in self._paginate(f"/repos/{owner}/{name}/issues/{number}/comments"):
                out.issue_comments.append(
                    Comment(body=c.get("body") or "", author=(c.get("user") or {}).get("login"))
                )
            for c in self._paginate(f"/repos/{owner}/{name}/pulls/{number}/comments"):
                out.review_comments.append(
                    Comment(
                        body=c.get("body") or "",
                        author=(c.get("user") or {}).get("login"),
                        path=c.get("path"),
                        line=c.get("line") or c.get("original_line"),
                    )
                )
        except httpx.HTTPError:
            pass
        return out

    # --- writes (phase 3) ---
    def post_review(
        self,
        owner: str,
        name: str,
        number: int,
        body: str,
        event: str,
        comments: list[dict] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"body": body, "event": event}
        if comments:
            payload["comments"] = comments
        r = self._send("POST", f"/repos/{owner}/{name}/pulls/{number}/reviews", json=payload)
        r.raise_for_status()
        return r.json()
