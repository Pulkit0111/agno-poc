# Bott Build & Fix — Design Spec (Phase 5)

- **Date:** 2026-06-30
- **Scope:** The flagship capability — Bott implements a change and opens a pull request,
  from a plain request, a GitHub issue, or a Jira ticket. "Fix a bug" is the same flow with
  a remediation framing.
- **Delivery:** Evolve the repo in place; new package `src/bott/agents/build_fix/` reusing the
  existing PR-review engine's auth/clone/worker/Slack machinery.
- **Roadmap:** Phase 5 of `docs/architecture/bott-target-architecture.md`. Activates the
  approval gate (built but dormant since the foundation). Builds on the completed foundation.

---

## 1. Goal

Let a person describe a change in Slack — or point Bott at a GitHub issue or Jira ticket — and
have Bott **understand → plan → (human approves) → implement → open a PR**, running the slow
work on the background worker. The PR is a draft proposal; merging stays a human decision.

## 2. Decisions (locked during brainstorming)

| Aspect | Choice |
|---|---|
| Triggers | NL request **+ GitHub issue + Jira ticket** — each populates the spec; identical downstream |
| Approval gate | On the **plan** — one gate, before any code is written |
| Execution | **In-process, fenced to the clone dir** (POC); production routes through `SandboxRunner` (Phase 4) |
| Fix-until-green | **Agent-discovered** test command; fix-attempt cap; **annotated-PR fallback** if tests can't run |
| Job architecture | **Two-job, non-blocking**: plan job → approve-click → implement job |
| Guardrail | Reuse `ALLOWED_POST_REPOS` as the single "repos Bott may write to" allowlist |
| PR | Opened as a **draft**; never merged by Bott |

## 3. End-to-end flow

```
"implement X" / owner/repo#issue / JIRA-KEY  →  start_build tool  →  enqueue PLAN job
                                                                          │
  PLAN job (worker): read ticket/issue + repo (read-only GitHub API, no clone) → draft plan
                     → post plan to the thread + Approve/Dismiss buttons
                     → create an approvals row carrying the implement payload (JSON)
                                                                          │
  user clicks Approve → existing button handler marks the row approved
                      → reads the payload → enqueues the IMPLEMENT job
                      (Dismiss → marks dismissed, posts a note, enqueues nothing)
                                                                          │
  IMPLEMENT job (worker): writable clone → agentic write/edit/test loop
                          (fix until green or cap) → push branch → open draft PR
                          → post PR link (or annotated/abandoned per the failure ladder)
```

No worker thread is ever blocked waiting on a human: the approve-*click* is what triggers the
next job, not a blocking poll.

## 4. The `approvals.payload` extension (foundation change)

The `approvals` table (from the foundation) stores `user_id, action, summary, status,
decided_by, created` — but no parameters. To let an Approve-click enqueue the implement job
with the right arguments, add a **nullable `payload` (JSON text) column** via an **Alembic
migration** (the first real use of the migration path). The approve handler dispatches by
action: an approved row whose `action` starts with `build:` → `queue.enqueue("implement",
json.loads(payload), user_id=<approver or original>)`. Generic: any future gated action gets a
"what to do on approve" slot. `schema.py`'s `APPROVALS` table gains the column; the migration
adds it to populated Postgres.

## 5. Components

New package `src/bott/agents/build_fix/` (sibling to `code_review/`):

| File | Responsibility | Reuse / new |
|---|---|---|
| `refs.py` | Parse the 3 trigger forms (NL text, `owner/repo#issue`, `JIRA-KEY`) → `BuildRequest` | new |
| `member.py` | `start_build(target, run_context) -> str` enqueue tool (the `start_review` pattern) | new (pattern reused) |
| `planner.py` | PLAN job: gather context (Jira read + GitHub-read API + Memra) → `ImplementPlan`; post plan blocks + buttons; create `approvals` row with payload | new |
| `pipeline.py` | `implement_task(...) -> ImplementResult`: writable clone → agent loop → push → PR | new (mirrors `review_pr`) |
| `agent/tools.py` | `ImplementTools`: read/grep/find/edit/write/run-shell over the clone (CodingTools-based) | new (CodingTools reused) |
| `agent/prompt.py` | Implement system prompt: discover tests, fix-until-green, scope discipline | new |
| `core/models.py` | `BuildRequest`, `ImplementPlan`, `ImplementResult` dataclasses | new |
| `rendering.py` | Slack blocks for the plan (+Approve/Dismiss buttons) and the result | new |
| `code_review/github/client.py` | extend `GitHubClient` with `push_branch(...)`, `create_pull(...)`, `default_branch(...)` | extend |
| `code_review/github/clone.py` | add `writable_clone(owner, name, *, token)` — clones the repo's default branch (full history), sets git identity + push auth | extend |
| `interfaces/slack_app.py` | add `plan` + `implement` branches to `handle_task` | extend |
| `interfaces/slack_home/router.py` | approve-handler: on approved `build:*` → enqueue implement from payload | extend |
| `shared/schema.py` + migration | `APPROVALS` gains `payload`; Alembic migration | extend |

### Reused as-is (verified)
- `app_token_for(owner, name)` (App installation token), `queue.enqueue/worker_main`,
  `handle_task` dispatch + `_post/_update/_react` Slack helpers, the approval-gate API
  (`create_request/decide/status`) + the existing Approve/Dismiss button **handler**,
  `CodingTools` (point `base_dir` at the clone).

## 6. The implement job internals

- **Writable clone:** `writable_clone` does a full clone of the default branch, sets
  `git config user.name/email` to a Bott identity, authenticates the remote via the App
  installation token. Same `CloneHandle` context-manager shape + auto-cleanup as `shallow_clone`.
- **Agent loop:** an Agno agent on the `"heavy"` model with `ImplementTools` over the clone.
  It inspects the repo, discovers the test command (README / `pyproject.toml` / `package.json`
  / `Makefile` / CI config), writes the change, runs tests in a subprocess (timeout + resource
  caps), reads failures, fixes, and re-runs — until green or the fix cap.
- **Budget** (`ImplementBudget`, env-overridable): `max_tool_calls` (default 40),
  `max_fix_attempts` (default 4), `max_tokens`, `max_usd`, wall-clock `timeout`. Any cap → stop
  and proceed to the result step with whatever exists.
- **Branch & PR:** branch `bott/<slug>-<short-id>`; base = auto-detected default branch; PR
  opened as a **draft**; body = approved plan + "what changed" + test status (✓ / ⚠ couldn't
  run) + `🤖 Generated with Claude Code` footer.

## 7. Failure ladder (never silent)

| Situation | Behavior |
|---|---|
| No tests found / can't run (missing deps, no runner) | Open the draft PR anyway, **annotated** "tests not found / couldn't run" in body + Slack |
| Tests still red after `max_fix_attempts` | Open a **draft PR** with the diff + "tests failing after N attempts" + last failure output |
| Agent produces an empty diff | **No PR**; post the agent's explanation to the thread |
| Push / PR API call fails | Post the diff to Slack as a fallback so work isn't lost |
| Repo not in `ALLOWED_POST_REPOS` | Refuse at the **plan** stage with a clear message; never clone-for-write |

## 8. Safety

- **Approval before any world change.** Nothing is cloned-for-write, pushed, or PR'd until a
  human approves the plan. The implement job re-checks the `approvals` status before pushing
  (defense in depth).
- **Isolation.** Both jobs carry the triggering user's `user_id` (system fallback for non-human
  paths), like reviews; `decided_by` records the approver.
- **Write fenced two ways:** the `ALLOWED_POST_REPOS` allowlist *and* the draft-PR default
  (always human-reviewed before merge).
- **Execution honesty.** In-process fenced execution is the documented POC trust boundary
  (same as a developer running the repo locally with their own token). Production multi-user
  MUST route the implement loop through `SandboxRunner` (Phase 4); the seam exists.

## 9. Prerequisite (operator setup, not code)

The **GitHub App must grant `contents:write` + `pull_requests:write`.** The review path needed
only read + PR-review-comment scope, so the App likely lacks write today. Without it, push/PR
calls 401/403. This is a gate-zero check; `scripts/eval_build.py` fails fast with a clear
message when the scope is missing.

**No PAT fallback for writes.** The read-only review path falls back to a `gh`-CLI PAT or
unauthenticated access when the App is not installed on a repo. That fallback does NOT apply to
the write path: pushing branches and opening PRs requires the GitHub App with `contents:write` +
`pull_requests:write`. If the App is absent or lacks write scope, the implement job posts an
honest error to the thread and stops — it never attempts a PAT-based push.

## 10. Testing

- **Unit (no tokens/network):** ref parsing (all 3 trigger forms → `BuildRequest`); plan job
  posts correct blocks + creates an `approvals` row carrying the payload; approve-handler
  enqueues an `implement` job from an approved `build:*` payload and does nothing on dismiss;
  `writable_clone` sets git identity + push auth; PR-body rendering; each failure-ladder branch
  with a faked agent result (empty diff → no PR; red-after-cap → draft; can't-run → annotated).
- **Migration:** the `approvals.payload` migration applies + round-trips on SQLite and live
  ephemeral Postgres.
- **Live gate (on-demand, spends tokens):** `scripts/eval_build.py` runs one real implement on
  a throwaway allowlisted repo end-to-end (clone → implement → tests → draft PR).
- Existing suites stay green.

## 11. Out of scope (later)

The real `SandboxRunner` implementation (Phase 4); Sentry triage (Phase 6, reuses this
implement job from an approved triage plan); auto-merge (never — humans merge); multi-repo /
cross-repo changes; non-GitHub forges.

## 12. Definition of done

- `start_build` accepts all three trigger forms and enqueues a `plan` job.
- The plan job posts an approve-gated plan; Approve enqueues `implement`, Dismiss does not.
- The implement job: writable clone → agent-discovered test loop with a fix cap → draft PR on
  an allowlisted repo, with the full failure ladder honored.
- `approvals.payload` column + Alembic migration, verified on SQLite + live Postgres.
- Nothing pushes/PRs without an approved row; repo allowlist enforced at plan stage.
- Unit suite green; `scripts/eval_build.py` completes one real end-to-end build.
