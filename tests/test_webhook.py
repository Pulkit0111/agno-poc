import hashlib
import hmac
import json

import pytest
from sqlalchemy import text

from bott.shared import db
from bott.shared.persistence import queue

SECRET = "testsecret123"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("REVIEW_SLACK_CHANNEL", "C_TEST")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "wh.db"))
    db.get_engine(fresh=True)
    queue.init_queue()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from bott.agents.code_review.webhook import router
    fa = FastAPI()
    fa.include_router(router)
    yield TestClient(fa)
    db.get_engine(fresh=True)


def _post(client, payload, event="pull_request", delivery="d1", good=True):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest() if good else "sha256=bad"
    return client.post("/webhook/github", content=body, headers={
        "X-Hub-Signature-256": sig, "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery, "Content-Type": "application/json"})


OPENED = {"action": "opened",
          "pull_request": {"number": 7, "draft": False, "title": "feat: x",
                           "user": {"login": "alice", "type": "User"}},
          "repository": {"name": "repo", "owner": {"login": "acme"}}}


def test_bad_signature(client):
    assert _post(client, OPENED, good=False).status_code == 401


def test_ping(client):
    assert _post(client, {}, event="ping").status_code == 200


def _all_jobs():
    with db.get_engine().begin() as c:
        return c.execute(text("SELECT args, user_id FROM jobs")).fetchall()


def test_opened_enqueues(client):
    assert _post(client, OPENED, delivery="d1").status_code == 202
    rows = _all_jobs()
    assert len(rows) == 1
    a = json.loads(rows[0][0])
    assert a["source"] == "github" and a["number"] == 7 and a["post_github"] is True
    assert a["title"] == "feat: x" and a["author"] == "alice"
    # webhook always uses the system user_id
    assert rows[0][1] == "system@axelerant.com"


def test_duplicate_delivery_skipped(client):
    _post(client, OPENED, delivery="dup")
    assert _post(client, OPENED, delivery="dup").status_code == 202
    rows = _all_jobs()
    assert len(rows) == 1  # only the first enqueued


def test_draft_skipped(client):
    p = {**OPENED, "pull_request": {**OPENED["pull_request"], "draft": True}}
    assert _post(client, p, delivery="d2").status_code == 202
    assert _all_jobs() == []


def test_bot_author_skipped(client):
    p = {**OPENED, "pull_request": {**OPENED["pull_request"],
         "user": {"login": "dependabot[bot]", "type": "Bot"}}}
    assert _post(client, p, delivery="d3").status_code == 202
    assert _all_jobs() == []


def test_closed_action_ignored(client):
    p = {**OPENED, "action": "closed"}
    assert _post(client, p, delivery="d4").status_code == 202


def _sync(sha):
    return {"action": "synchronize",
            "pull_request": {"number": 7, "draft": False, "title": "feat: x",
                             "user": {"login": "alice", "type": "User"},
                             "head": {"sha": sha}},
            "repository": {"name": "repo", "owner": {"login": "acme"}}}


def test_synchronize_enqueues(client):
    assert _post(client, _sync("abc123"), delivery="s1").status_code == 202
    rows = _all_jobs()
    assert len(rows) == 1 and json.loads(rows[0][0])["source"] == "github"


def test_same_commit_deduped(client):
    _post(client, _sync("samesha"), delivery="s1")
    # a second synchronize for the same head SHA (different delivery id) is skipped
    assert _post(client, _sync("samesha"), delivery="s2").status_code == 202
    rows = _all_jobs()
    assert len(rows) == 1  # only the first enqueued
