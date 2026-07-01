# Phase 6 — Sentry triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Read a Sentry incident, diagnose it, propose a fix, and on approval flow the fix into the existing Build & Fix implement pipeline (clone → fix → draft PR).

**Architecture:** A `start_triage(sentry_issue_id, repo)` tool enqueues a `"triage"` job; the worker reads the issue + events, an agent diagnoses + writes a fix brief, the allowlist is enforced, and an approval (`action="triage:implement"`, payload shaped like a build plan) is posted. Approve routes through the existing `dispatch_approved_build` (extended for the `triage:` prefix) → `implement` job. Diagnosis IS the plan.

**Tech Stack:** Python 3.12, existing queue/approvals/build_fix machinery, Agno agent (`build_model`), pytest.

Spec: `docs/superpowers/specs/2026-07-01-bott-sentry-triage-design.md`

## Global Constraints

- **Propose-only:** triage reads + diagnoses + proposes; no code is written until a human approves. No Sentry write ops.
- **Implement-path invariant (load-bearing):** `dispatch_approved_build` (router.py:360) is the ONLY path that enqueues `"implement"`, reachable only from an approved, ALLOWLISTED, payload-bearing approvals row. `run_triage_job` MUST enforce the same allowlist (`f"{owner}/{name}".lower() in allowed_post_repos()`) BEFORE creating its approval, and produce the same payload shape (`{owner, name, plan_text, channel, thread_ts}`). Only then may `dispatch_approved_build` accept the `triage:` prefix.
- **Human supplies the repo:** a Sentry issue has no repo; `start_triage` requires `repo="owner/name"`. No project→repo inference.
- **Templates:** `src/bott/agents/code_review/member.py` (`start_review`/`_resolve_target`/`review_tools`), `src/bott/agents/build_fix/planner.py` (`run_plan_job`: allowlist gate + create_approval + post, injectable deps), `src/bott/agents/build_fix/rendering.py` (`plan_blocks`: Approve/Dismiss buttons with action_ids `approval_approve`/`approval_dismiss`), `src/bott/interfaces/slack_app.py:167` (`handle_task` job routing).
- Process: in-place on `main`, commit-only, no push, no worktree.

---

### Task 1: triage member + job + rendering + diagnosis

**Files:** Create `src/bott/agents/triage/__init__.py`, `member.py`, `triage.py`, `rendering.py`, `agent/prompt.py`; Test `tests/test_triage_member.py`, `tests/test_triage_job.py`.

**Interfaces produced:**
- `triage.member.start_triage(sentry_issue_id: str, repo: str, run_context=None) -> str`; `triage_tools() -> list[Callable]`.
- `triage.triage.run_triage_job(args, *, post, create_approval, fetch=None, diagnose=None) -> dict`.
- `triage.rendering.triage_blocks(diagnosis: str, permalink: str, approval_id: int) -> tuple[list, str]`.
- `triage.triage._default_fetch(sentry_issue_id) -> tuple[dict, list]`; `triage.triage._default_diagnose(issue, events) -> tuple[str, str]`.

- [ ] **Step 1: Write `tests/test_triage_member.py`**

```python
from types import SimpleNamespace

from bott.agents.triage import member


def test_start_triage_enqueues(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue",
                        lambda kind, args, user_id: calls.append((kind, args, user_id)) or 1)
    ctx = SimpleNamespace(user_id="alice@x.com",
                          dependencies={"Slack channel_id": "C1", "Slack thread_ts": "t1"})
    msg = member.start_triage("12345", "axelerant/foo", run_context=ctx)
    assert calls and calls[0][0] == "triage"
    _, args, user_id = calls[0]
    assert args["sentry_issue_id"] == "12345"
    assert args["owner"] == "axelerant" and args["name"] == "foo"
    assert args["channel"] == "C1" and args["thread_ts"] == "t1"
    assert user_id == "alice@x.com"
    assert "12345" in msg


def test_start_triage_rejects_bad_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(member.queue, "enqueue", lambda *a, **k: calls.append(a) or 1)
    out = member.start_triage("12345", "not-a-repo")
    assert "owner/name" in out.lower() or "repo" in out.lower()
    assert not calls  # nothing enqueued


def test_triage_tools_exposes_start_triage():
    assert any(getattr(t, "__name__", "") == "start_triage" for t in member.triage_tools())
```

- [ ] **Step 2: Write `tests/test_triage_job.py`**

```python
import json

from bott.agents.triage import triage


_ISSUE = {"id": "12345", "shortId": "FOO-1", "title": "KeyError in checkout",
          "level": "error", "permalink": "https://sentry.io/o/i/12345", "count": "9"}
_EVENTS = [{"eventID": "e1", "message": "KeyError: 'sku'", "environment": "prod"}]


def _job(**over):
    args = {"sentry_issue_id": "12345", "owner": "axelerant", "name": "foo",
            "channel": "C1", "thread_ts": "t1", "user_id": "alice@x.com"}
    args.update(over)
    return args


def test_run_triage_job_creates_approval_and_posts(monkeypatch):
    monkeypatch.setattr(triage, "allowed_post_repos", lambda: {"axelerant/foo"})
    posts, approvals = [], []
    out = triage.run_triage_job(
        _job(),
        post=lambda ch, ts, blocks, fb: posts.append((ch, ts, blocks, fb)),
        create_approval=lambda **kw: approvals.append(kw) or 77,
        fetch=lambda sid: (_ISSUE, _EVENTS),
        diagnose=lambda issue, events: ("Root cause: missing sku key.", "Add a guard for missing 'sku'."),
    )
    assert out["status"] == "awaiting_approval" and out["approval_id"] == 77
    assert approvals and approvals[0]["action"] == "triage:implement"
    payload = json.loads(approvals[0]["payload"])
    assert payload == {"owner": "axelerant", "name": "foo",
                       "plan_text": "Add a guard for missing 'sku'.",
                       "channel": "C1", "thread_ts": "t1"}
    assert posts and posts[0][0] == "C1"


def test_run_triage_job_refuses_when_not_allowlisted(monkeypatch):
    monkeypatch.setattr(triage, "allowed_post_repos", lambda: set())  # empty allowlist
    posts, approvals = [], []
    out = triage.run_triage_job(
        _job(),
        post=lambda ch, ts, blocks, fb: posts.append((ch, ts, blocks, fb)),
        create_approval=lambda **kw: approvals.append(kw) or 1,
        fetch=lambda sid: (_ISSUE, _EVENTS),
        diagnose=lambda issue, events: ("d", "b"),
    )
    assert out["status"] == "refused_not_allowlisted"
    assert not approvals  # INVARIANT: no approval created for a non-allowlisted repo
    assert posts  # a refusal was posted
```

- [ ] **Step 3: Run, expect fail** — `ModuleNotFoundError: …agents.triage`.

- [ ] **Step 4: Implement `src/bott/agents/triage/member.py`** (mirror `code_review/member.py`):

```python
from __future__ import annotations

import contextvars
from typing import Callable, Optional

from agno.run.base import RunContext

from bott.shared import queue
from bott.shared.config import bott_model

_triage_target: contextvars.ContextVar = contextvars.ContextVar("triage_target", default=None)


def _resolve_target(run_context: Optional[RunContext]) -> dict:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    channel = deps.get("Slack channel_id")
    if channel:
        return {"channel": channel, "thread_ts": deps.get("Slack thread_ts")}
    return _triage_target.get() or {}


def start_triage(sentry_issue_id: str, repo: str, run_context: Optional[RunContext] = None) -> str:
    """Triage a Sentry incident: read it, diagnose it, propose a fix, await approval, then
    implement. `sentry_issue_id`: the Sentry issue id. `repo`: the `owner/name` GitHub repo to
    fix (Sentry doesn't know the repo — you must name it)."""
    parts = (repo or "").strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return "Tell me which repo to fix as `owner/name` (e.g. `axelerant/foo`)."
    owner, name = parts[0], parts[1]
    sid = (sentry_issue_id or "").strip()
    if not sid:
        return "Which Sentry issue? Give me its id."
    t = _resolve_target(run_context)
    user_id = getattr(run_context, "user_id", None) or "system@axelerant.com"
    queue.enqueue("triage", {
        "sentry_issue_id": sid, "owner": owner, "name": name,
        "channel": t.get("channel"), "thread_ts": t.get("thread_ts"),
        "model_id": bott_model(),
    }, user_id=user_id)
    return f"Queued triage of Sentry issue {sid} in {owner}/{name} — I'll diagnose it and post a proposed fix for approval."


def triage_tools() -> list[Callable]:
    return [start_triage]
```

- [ ] **Step 5: Implement `src/bott/agents/triage/rendering.py`** (reuse the Approve/Dismiss button shape from `build_fix/rendering.plan_blocks`):

```python
from __future__ import annotations


def triage_blocks(diagnosis: str, permalink: str, approval_id: int) -> tuple[list, str]:
    link = f"\n<{permalink}|View in Sentry>" if permalink else ""
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Sentry triage — proposed fix*\n{diagnosis}{link}"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve & implement"},
             "style": "primary", "action_id": "approval_approve", "value": str(approval_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "Dismiss"},
             "action_id": "approval_dismiss", "value": str(approval_id)},
        ]},
    ]
    return blocks, "Sentry triage — proposed fix (approve to implement)."
```

- [ ] **Step 6: Implement `src/bott/agents/triage/agent/prompt.py`**

```python
TRIAGE_SYSTEM = (
    "You are triaging a production incident from Sentry. Given the issue and its recent "
    "events, explain the ROOT CAUSE in 3-5 plain sentences, then write a concise, actionable "
    "FIX BRIEF a developer could implement (what to change and where, at a high level). "
    "Return the diagnosis first, then a line 'FIX:' followed by the brief."
)
```

- [ ] **Step 7: Implement `src/bott/agents/triage/triage.py`**

```python
from __future__ import annotations

import json
from typing import Callable

from bott.agents.triage import rendering
from bott.shared.config import allowed_post_repos, sentry_configured
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.triage")


def _default_fetch(sentry_issue_id: str):
    from bott.shared import config
    from bott.shared.integrations.sentry import SentryClient
    c = SentryClient(base_url=config.sentry_base_url(), org_slug=config.sentry_org_slug(),
                     api_token=config.sentry_api_token())
    return c.get_issue(sentry_issue_id), c.issue_events(sentry_issue_id, limit=5)


def _default_diagnose(issue: dict, events: list) -> tuple[str, str]:
    """Run the diagnosis agent; split its output into (diagnosis, fix_brief)."""
    from agno.agent import Agent
    from bott.agents.triage.agent.prompt import TRIAGE_SYSTEM
    from bott.shared.model import build_model
    context = json.dumps({"issue": issue, "events": events}, default=str)[:6000]
    agent = Agent(model=build_model("heavy"), instructions=TRIAGE_SYSTEM)
    out = agent.run(f"Triage this incident:\n{context}").content or ""
    if "FIX:" in out:
        diag, brief = out.split("FIX:", 1)
        return diag.strip(), brief.strip()
    return out.strip(), out.strip()


def run_triage_job(args: dict, *, post: Callable, create_approval: Callable,
                   fetch: Callable | None = None, diagnose: Callable | None = None) -> dict:
    """Read the Sentry issue, diagnose it, enforce the write allowlist, create the implement
    approval (payload shaped like a build plan) and post the diagnosis + Approve/Dismiss.
    Deps injected for offline tests (like run_plan_job)."""
    owner, name = args["owner"], args["name"]
    channel, thread_ts = args.get("channel"), args.get("thread_ts")
    if not sentry_configured():
        if channel:
            post(channel, thread_ts, [{"type": "section", "text": {"type": "mrkdwn",
                 "text": "Sentry isn't configured (set SENTRY_ORG_SLUG, SENTRY_API_TOKEN)."}}],
                 "Sentry not configured.")
        return {"status": "sentry_unconfigured", "approval_id": None}
    if f"{owner}/{name}".lower() not in allowed_post_repos():
        if channel:
            post(channel, thread_ts, [{"type": "section", "text": {"type": "mrkdwn",
                 "text": f"I can't open PRs on `{owner}/{name}` (not in the allowlist)."}}],
                 "Repo not allow-listed.")
        return {"status": "refused_not_allowlisted", "approval_id": None}

    fetch = fetch or _default_fetch
    diagnose = diagnose or _default_diagnose
    try:
        issue, events = fetch(args["sentry_issue_id"])
    except Exception as e:  # noqa: BLE001
        log.error("triage fetch failed: %s", e)
        if channel:
            post(channel, thread_ts, [{"type": "section", "text": {"type": "mrkdwn",
                 "text": "Couldn't read that Sentry issue."}}], "Sentry read failed.")
        return {"status": "fetch_failed", "approval_id": None}
    diagnosis, brief = diagnose(issue, events)
    payload = json.dumps({"owner": owner, "name": name, "plan_text": brief,
                          "channel": channel, "thread_ts": thread_ts})
    approval_id = create_approval(user_id=args.get("user_id") or "system@axelerant.com",
                                  action="triage:implement",
                                  summary=f"Fix {owner}/{name} (Sentry {args['sentry_issue_id']}): {brief[:80]}",
                                  payload=payload)
    blocks, fallback = rendering.triage_blocks(diagnosis, issue.get("permalink", ""), approval_id)
    if channel:
        post(channel, thread_ts, blocks, fallback)
    return {"status": "awaiting_approval", "approval_id": approval_id}
```

- [ ] **Step 8: Create `src/bott/agents/triage/__init__.py`** (`from bott.agents.triage.member import triage_tools`) and `src/bott/agents/triage/agent/__init__.py` (empty).

- [ ] **Step 9: Run tests green** — `.venv/bin/python -m pytest tests/test_triage_member.py tests/test_triage_job.py -v` (6 tests). Ruff the new files.

- [ ] **Step 10: Commit** — `git commit -m "feat(triage): Sentry triage member + job (diagnose → allowlisted approval → implement payload)"`

---

### Task 2: wire triage into dispatch, worker, and agent

**Files:** Modify `src/bott/interfaces/slack_home/router.py`, `src/bott/interfaces/slack_app.py`, `src/bott/agents/bott_agent.py`; Test `tests/test_triage_dispatch.py`.

- [ ] **Step 1: Write `tests/test_triage_dispatch.py`**

```python
import json

from bott.interfaces.slack_home import router
from bott.shared import approvals, db


def _store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "d.db"))
    db.get_engine(fresh=True)
    approvals.init_approvals()


def test_dispatch_enqueues_implement_for_approved_triage(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    enq = []
    monkeypatch.setattr(router.queue, "enqueue",
                        lambda kind, payload, user_id, dedup_key=None: enq.append((kind, payload, dedup_key)) or 1)
    payload = json.dumps({"owner": "axelerant", "name": "foo", "plan_text": "fix it",
                          "channel": "C1", "thread_ts": "t1"})
    aid = approvals.create_request("alice@x.com", "triage:implement", "Fix foo", payload=payload)
    approvals.decide(aid, approved=True, decided_by="alice@x.com")
    router.dispatch_approved_build(aid)
    assert enq and enq[0][0] == "implement"
    assert enq[0][1]["owner"] == "axelerant" and enq[0][1]["plan_text"] == "fix it"


def test_dispatch_ignores_unapproved_triage(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path)
    enq = []
    monkeypatch.setattr(router.queue, "enqueue", lambda *a, **k: enq.append(a) or 1)
    aid = approvals.create_request("u", "triage:implement", "x", payload="{}")
    router.dispatch_approved_build(aid)  # still pending
    assert not enq
```

- [ ] **Step 2: Run, expect fail** — dispatch ignores `triage:` (only handles `build:`), so `test_dispatch_enqueues_implement_for_approved_triage` fails.

- [ ] **Step 3: Extend `dispatch_approved_build`** (`router.py:360`) — widen the action guard and update the invariant docstring:

Change the guard line from:
```python
    if not row or row.get("status") != "approved" or not str(row.get("action", "")).startswith("build:"):
        return
```
to:
```python
    if not row or row.get("status") != "approved" or not str(row.get("action", "")).startswith(("build:", "triage:")):
        return
```
And update the docstring to note: "Enqueues the implement job for an approved `build:*` OR `triage:*` row. Both stages (build plan, sentry triage) are payload producers that enforce the write allowlist BEFORE creating their approval, so this remains the only implement path and every implement is allowlisted."

- [ ] **Step 4: Route the `"triage"` kind in the worker** (`slack_app.py`, in `handle_task`, mirror the `"plan"` branch at ~line 179-185):

```python
    if task["kind"] == "triage":
        from bott.agents.triage.triage import run_triage_job
        from bott.shared.approvals import create_request
        run_triage_job(a, post=_post, create_approval=create_request)
        return
```
(Place it beside the other `if task["kind"] == …` branches; use the same `_post` + `a = task["args"]` + channel/thread already established in `handle_task`.)

- [ ] **Step 5: Wire the tool** (`bott_agent.py`) — add `from bott.agents.triage import triage_tools` and, next to `tools.extend(review_tools())`:
```python
    tools.extend(triage_tools())  # Sentry triage: diagnose → approve → implement
```

- [ ] **Step 6: Run tests + full suite** — `.venv/bin/python -m pytest tests/test_triage_dispatch.py tests/test_triage_member.py tests/test_triage_job.py -v`, then `.venv/bin/python -m pytest -q` (expect prior 436 + 6 + 2 = 444 passed / 2 skipped; report actual). Ruff `src/bott/agents/triage/ src/bott/interfaces/slack_home/router.py src/bott/interfaces/slack_app.py src/bott/agents/bott_agent.py`.

- [ ] **Step 7: Commit** — `git commit -m "feat(triage): wire Sentry triage (dispatch triage:implement → build implement worker; agent tool)"`

---

## Self-Review

- Spec coverage: flow §1 → T1 (member+job) + T2 (dispatch/worker/agent); invariant §2 → T1 allowlist gate + T2 dispatch guard; components §3 → both tasks; testing §5 → the three test files. ✓
- Invariant preserved: `run_triage_job` allowlist-checks before `create_approval`; `test_run_triage_job_refuses_when_not_allowlisted` asserts no approval created; dispatch only enqueues implement for approved allowlisted-produced rows. ✓
- Propose-only: no implement enqueue except via approve→dispatch; triage creates only an approval. ✓
- Placeholders: full code for member/triage/rendering/prompt + all tests; integration edits point at exact files/lines with the exact change. ✓
- Type consistency: `run_triage_job(args, *, post, create_approval, fetch, diagnose)`, payload keys `{owner,name,plan_text,channel,thread_ts}` (matches run_plan_job + dispatch), `triage_tools`/`start_triage` names consistent across tasks, spec, tests. ✓
