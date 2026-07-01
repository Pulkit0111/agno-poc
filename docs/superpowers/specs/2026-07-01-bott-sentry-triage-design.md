# Phase 6 — Sentry triage Design

**Date:** 2026-07-01
**Status:** build (part of the "build the whole app per the doc" mandate)
**Scope:** Sentry **triage** — read a Sentry incident, diagnose it, propose a fix, and (on approval) flow the fix into the existing Build & Fix implement pipeline (clone → fix → draft PR). Reuses the Sentry read connector (Phase 4), the job queue, the approval gate, and the Build & Fix implement worker. PR review (the other half of Phase 6) already exists.

Architecture doc: Phase 6 "Review & triage" — "Agentic PR review ✅ + Sentry triage (reuses Build & Fix)"; §ontriage: "read an incident, explain it, propose a fix; an approved fix flows back into Build & Fix." **Propose-only** — no auto-fix without approval.

---

## 1. Flow (two stages, approval between)

1. **Trigger:** user calls `start_triage(sentry_issue_id, repo)` in Slack (e.g. "triage sentry issue 12345 in axelerant/foo"). `repo` = the `owner/name` to fix — **required**, because a Sentry issue does not name a repository. Enqueues a `"triage"` job.
2. **Stage 1 — diagnose (worker):** `run_triage_job` reads the issue + recent events via `SentryClient`, runs a diagnosis agent (Sentry context + a triage prompt) to produce a **diagnosis** (root cause, plain-language) + a **fix brief** (actionable implement instructions). It **enforces the write allowlist** on `owner/name` (mirroring `run_plan_job`), creates an approval `action="triage:implement"` carrying the Build & Fix implement payload `{owner, name, plan_text=<fix brief>, channel, thread_ts}`, and posts the diagnosis + Approve/Dismiss to the Slack thread.
3. **Approve → implement:** the existing approve button routes through `dispatch_approved_build`, which (extended to accept the `triage:` prefix) enqueues the `"implement"` job from the payload. From here it is **identical** to Build & Fix: the implement worker clones the repo, fixes until green, and opens a draft PR. Dismiss = nothing happens.

Triage's diagnosis *is* the plan — there's no separate plan stage (the diagnosis already reasons about the fix), so triage feeds the implement stage directly, exactly as an approved build plan does.

---

## 2. Reuse & the implement-path invariant (load-bearing)

`dispatch_approved_build` (router.py:360) is documented as the ONLY path that enqueues an `"implement"` job, reachable only from an **approved, allowlisted, payload-bearing** approvals row — the plan stage being the sole payload producer + allowlist gate. Sentry triage becomes a **second** payload producer, so it MUST uphold the same contract:

- `run_triage_job` performs the **same allowlist check** as `run_plan_job` (`f"{owner}/{name}".lower() in allowed_post_repos()`) BEFORE creating the approval; if not allowlisted, it posts a refusal and creates no approval.
- The approval payload has the **same shape** run_plan_job produces (`owner, name, plan_text, channel, thread_ts`).
- `dispatch_approved_build`'s guard is widened from `action.startswith("build:")` to also accept `"triage:"`, and its invariant docstring is updated to name triage as the second allowlist-gated producer.

This keeps the "only allowlisted, approved rows reach implement" invariant true.

---

## 3. Components

**New package `src/bott/agents/triage/`:**

- `member.py`:
  - `start_triage(sentry_issue_id: str, repo: str, run_context=None) -> str` — parse `repo` into `owner/name` (reuse a simple `owner/name` split; reject malformed with a helpful message); resolve Slack target from run_context (like `code_review.member._resolve_target`); enqueue `"triage"` with `{sentry_issue_id, owner, name, channel, thread_ts, model_id, user_id}`; return "Queued triage of Sentry issue N in owner/name."
  - `triage_tools() -> list[Callable]` → `[start_triage]`.
- `triage.py`:
  - `run_triage_job(args, *, post, create_approval, fetch=None, diagnose=None) -> dict` — injectable deps (like `run_plan_job`): `fetch(sentry_issue_id) -> (issue: dict, events: list[dict])` (default uses `SentryClient` from config); `diagnose(issue, events) -> (diagnosis_text: str, fix_brief: str)` (default runs the triage agent). Steps: allowlist-check `owner/name` (refuse+post if not); `issue, events = fetch(...)`; `diagnosis, brief = diagnose(issue, events)`; `create_approval(user_id, action="triage:implement", summary, payload=json{owner,name,plan_text=brief,channel,thread_ts})`; `post(channel, thread_ts, blocks, fallback)`. Returns `{status, approval_id}`.
- `agent/prompt.py` + `agent/runner.py` (or a `_default_diagnose`): builds a diagnosis agent with `build_model("heavy")` + the Sentry issue/events context; prompt: "You are triaging a production incident. Given the Sentry issue and recent events, explain the root cause in 3-5 sentences, then write a concise, actionable fix brief a developer could implement." Returns (diagnosis, brief).
- `rendering.py`: `triage_blocks(diagnosis_text, issue, approval_id)` — Slack blocks showing the diagnosis + issue link (permalink) + Approve/Dismiss buttons. **Reuse** `build_fix.rendering.plan_blocks`' Approve/Dismiss button construction (same `approval_approve`/`approval_dismiss` action_ids the router already handles) — either call it with the brief as the plan summary, or mirror its button block exactly.

**Extend:**

- `src/bott/interfaces/slack_home/router.py` — `dispatch_approved_build`: accept `action` prefix `build:` OR `triage:`; update the invariant docstring.
- The worker task dispatcher (where `handle_task`/job-kind routing lives, e.g. `interfaces/slack_app.py` or the worker module) — add `elif kind == "triage": run_triage_job(args, post=<real post>, create_approval=<approvals.create_request>)` wiring the real Sentry fetch + diagnosis agent + Slack post (mirror how the `"plan"` kind wires `run_plan_job`).
- `src/bott/agents/bott_agent.py` — `tools.extend(triage_tools())` alongside `build_tools()`/`review_tools()`.

---

## 4. Config / prerequisites

No new config — reuses the Phase 4 Sentry connector config (`SENTRY_ORG_SLUG`, `SENTRY_API_TOKEN`) and the Build & Fix `ALLOWED_POST_REPOS` allowlist + GitHub App. If Sentry isn't configured, `start_triage`/`run_triage_job` return the same "Sentry isn't configured" message the read tools use (gate on `config.sentry_configured()`).

---

## 5. Testing (mirror `test_build_member.py` / build_fix planner tests — inject deps, no live calls)

- **member:** `start_triage` enqueues a `"triage"` job with `sentry_issue_id`, parsed `owner/name`, channel/thread from run_context, and user_id; malformed `repo` → helpful refusal, no enqueue; `triage_tools()` exposes `start_triage`.
- **run_triage_job (deps injected):** with a stub `fetch` (canned issue+events) and stub `diagnose` (returns fixed diagnosis+brief): creates an approval with `action="triage:implement"` and payload `{owner,name,plan_text=brief,channel,thread_ts}`; posts diagnosis blocks; returns `awaiting_approval` + approval_id. **Allowlist:** when `owner/name` not in `allowed_post_repos()`, it refuses (posts refusal, creates NO approval, status `refused_not_allowlisted`) — the invariant-preserving test. Sentry-unconfigured → graceful message.
- **dispatch extension:** an approved row with `action="triage:implement"` + payload → `dispatch_approved_build` enqueues an `"implement"` job with that payload (mirror the existing build:implement dispatch test); a non-approved or wrong-action row → no-op.
- **wiring:** `bott_agent` includes `start_triage`; the worker dispatcher routes `"triage"` to `run_triage_job` (unit-test the routing branch if the dispatcher is testable, else assert the handler mapping).

## 6. Files

| File | Change |
|---|---|
| `src/bott/agents/triage/member.py` | **create** — `start_triage`, `triage_tools` |
| `src/bott/agents/triage/triage.py` | **create** — `run_triage_job` (injectable deps, allowlist gate) |
| `src/bott/agents/triage/agent/prompt.py` + diagnosis runner | **create** — default diagnosis agent |
| `src/bott/agents/triage/rendering.py` | **create** — diagnosis + Approve/Dismiss blocks (reuse plan_blocks buttons) |
| `src/bott/agents/triage/__init__.py` | **create** — export `triage_tools` |
| `src/bott/interfaces/slack_home/router.py` | `dispatch_approved_build` accepts `triage:` (invariant doc updated) |
| worker task dispatcher | route `"triage"` kind → `run_triage_job` |
| `src/bott/agents/bott_agent.py` | wire `triage_tools()` |
| `tests/test_triage_member.py`, `tests/test_triage_job.py`, `tests/test_triage_dispatch.py` | **create** |

## 7. Non-goals

Auto-fix without approval; inferring the repo from Sentry (the human supplies it — no speculative project→repo mapping); resolving/assigning/commenting on the Sentry issue (write ops — deferred); a separate triage plan stage (diagnosis is the plan). Scheduled/proactive triage of new incidents (a later enhancement; this is on-demand via `start_triage`).
