# FINAL-REVIEW Fix Wave Report

**Date:** 2026-06-30  
**Branch:** main (in-place)

---

## Fixes Applied

### Fix 1 — Token leak: redact git push error (pipeline.py)
- Added `redact` to the import from `bott.shared.observability.logging_setup` in `pipeline.py`.
- Changed `raise RuntimeError(f"git push failed: {push.stderr.strip()}")` to use `redact(push.stderr.strip())`.
- File: `src/bott/agents/build_fix/pipeline.py`

### Fix 2 — Silent failure + 3x retry prevention (slack_app.py)
- Extracted the implement-branch body into a new `_run_implement(a, channel, thread_ts)` helper at module level. This keeps `handle_task` clean and makes the logic independently unit-testable.
- Wrapped `implement_task(...)` in try/except. On exception: logs the error, posts honest failure to Slack, returns normally (so `worker_main` marks job done, no retry).
- `handle_task` now delegates to `_run_implement` via a single call.

### Fix 3 — No-token guard, honest trust model (slack_app.py)
- Added an explicit `if not gh_token:` guard in `_run_implement`: posts the "GitHub App needs write access" message to the thread and returns without attempting a build.
- Added `redact` to `_post`'d error text so no token leaks into Slack.
- File: `src/bott/interfaces/slack_app.py`

### Fix 4 — Invariant comment (router.py)
- Added a 4-line `# INVARIANT:` comment immediately above `queue.enqueue("implement", ...)` in `dispatch_approved_build` in `router.py`.
- File: `src/bott/interfaces/slack_home/router.py`

### Fix 5a — Cheap minor: approvals.py get_request (approvals.py)
- Changed `get_engine().begin()` → `get_engine().connect()` in `get_request` (pure SELECT, no write transaction needed).
- Row-to-dict still works under `connect()` since `._mapping` is available on any SQLAlchemy row object.
- File: `src/bott/shared/approvals.py`

### Fix 5b — Cheap minor: config.py branch name comment (config.py)
- Updated the misleading "determinism" comment in `_build_branch_name`. New comment explains Python's `hash()` is per-process PRNG-seeded (`PYTHONHASHSEED`), so the suffix is NOT stable across restarts — this is fine for intra-process uniqueness, not cross-process determinism.
- No behavior change.
- File: `src/bott/shared/config.py`

### Fix 6 — Doc reconciliation: PAT fallback (spec doc)
- Added a "No PAT fallback for writes" paragraph to Section 9 (Prerequisite) of the build-fix design spec.
- Clarifies: the read-only review path's gh-CLI/PAT fallback does NOT apply to pushing branches or opening PRs. The write path requires the GitHub App with `contents:write` + `pull_requests:write`; absent that, the job posts an honest error and stops.
- File: `docs/superpowers/specs/2026-06-30-bott-build-fix-design.md`

---

## Tests Added

**File:** `tests/test_build_wiring.py` (2 new tests appended)

**Approach chosen:** Extracted `_run_implement` helper and unit-tested it directly. This was the lowest-risk approach — `handle_task` is entangled with Slack reactions, progress updates, and review/rereview logic that requires extensive mocking. The helper closes over no outer state, so it's directly testable with monkeypatching.

The lazy imports of `implement_task` and `result_blocks` inside `_run_implement` are intercepted via `sys.modules` injection (standard pytest monkeypatch), so tests run fully offline.

### test_run_implement_no_token_posts_no_access_and_does_not_call_implement
- `app_token_for` returns `None`.
- Asserts: `implement_task` is NOT called; exactly one Slack post with "write access" language.

### test_run_implement_exception_posts_failure_and_does_not_propagate
- `app_token_for` returns a fake token; `implement_task` raises `RuntimeError`.
- Asserts: function returns normally (no propagation); one Slack post with "couldn't complete" language.

---

## Verification

| Check | Result |
|---|---|
| `pytest -q` | **353 passed, 1 skipped** (was 351; 2 new tests added) |
| `ruff check src tests scripts` | **All checks passed!** |
| App construct check | **ok True** |

---

## Files Changed

1. `src/bott/agents/build_fix/pipeline.py` — Fix 1 (redact push error)
2. `src/bott/interfaces/slack_app.py` — Fix 2+3 (extract helper, no-token guard, try/except)
3. `src/bott/interfaces/slack_home/router.py` — Fix 4 (invariant comment)
4. `src/bott/shared/approvals.py` — Fix 5a (connect instead of begin)
5. `src/bott/shared/config.py` — Fix 5b (comment correction)
6. `docs/superpowers/specs/2026-06-30-bott-build-fix-design.md` — Fix 6 (no PAT fallback note)
7. `tests/test_build_wiring.py` — 2 new tests
8. `.superpowers/sdd/final-fix-report.md` — this report

## Deferred

Nothing deferred. All 6 fixes applied, tests passing, suite green, ruff clean, app constructs.
