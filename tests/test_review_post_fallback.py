"""Posting a finished review must never lose the review.

GitHub returns 422 for APPROVE/REQUEST_CHANGES on a PR the App itself authored (Bott
reviewing its own build PR), and for comment anchors it rejects. The post ladder degrades:
full review → COMMENT event → body-only COMMENT → give up gracefully (posted=None +
post_error), so the Slack verdict still lands.
"""

from __future__ import annotations

import httpx

from bott.agents.code_review.core.pipeline import _post_with_fallback


class _Rendered:
    body = "review body"
    event = "REQUEST_CHANGES"


def _422():
    req = httpx.Request("POST", "https://api.github.com/x")
    return httpx.HTTPStatusError("422", request=req,
                                 response=httpx.Response(422, request=req, text="Unprocessable"))


class _GhLadder:
    """422s until `fail_first` calls have been made, then succeeds."""

    def __init__(self, fail_first: int):
        self.fail_first = fail_first
        self.calls: list[dict] = []

    def post_review(self, owner, name, number, body, event, comments=None):
        self.calls.append({"event": event, "comments": comments, "body": body})
        if len(self.calls) <= self.fail_first:
            raise _422()
        return {"html_url": "https://github.com/o/r/pull/4#review"}


def test_posts_directly_when_allowed():
    gh = _GhLadder(fail_first=0)
    posted, err = _post_with_fallback(gh, "o", "r", 4, _Rendered(), [{"path": "a", "line": 1}])
    assert posted and err == ""
    assert gh.calls[0]["event"] == "REQUEST_CHANGES"


def test_422_downgrades_to_comment_event():
    """Own-PR case: REQUEST_CHANGES 422s → retried as a COMMENT review, verdict noted in body."""
    gh = _GhLadder(fail_first=1)
    posted, err = _post_with_fallback(gh, "o", "r", 4, _Rendered(), [{"path": "a", "line": 1}])
    assert posted and err == ""
    assert gh.calls[1]["event"] == "COMMENT"
    assert "REQUEST_CHANGES" in gh.calls[1]["body"]  # intended verdict preserved in prose
    assert gh.calls[1]["comments"]  # inline comments kept on the first fallback


def test_second_422_drops_inline_comments():
    """Anchor-reject case: COMMENT with comments still 422s → body-only COMMENT."""
    gh = _GhLadder(fail_first=2)
    posted, err = _post_with_fallback(gh, "o", "r", 4, _Rendered(), [{"path": "a", "line": 1}])
    assert posted and err == ""
    assert gh.calls[2]["event"] == "COMMENT" and not gh.calls[2]["comments"]


def test_total_failure_returns_error_never_raises():
    gh = _GhLadder(fail_first=99)
    posted, err = _post_with_fallback(gh, "o", "r", 4, _Rendered(), [])
    assert posted is None and "422" in err
