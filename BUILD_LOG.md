# Agno POC — Build Log

> Running log of what was built, decisions made, and time/effort spent.
> This log is itself a POC deliverable (feeds the Hermes comparison).

---

## 2026-06-15 — Session 1: Grounding + isolation mechanism research

### What I found in the workspace
- This directory (`/Users/pulkittyagi/Desktop/agno`) is **not Bott** — it's a fresh Agno scaffold.
  - `workbench.py`: single "Workbench" agent on AgentOS (`openai:gpt-4o-mini`, `SqliteDb`,
    `enable_agentic_memory=True`, `Workspace(".")` tool). ~27 lines.
  - `agent-ui/`: stock Agno Next.js frontend.
  - `.env`: has `OPENAI_API_KEY`; `ANTHROPIC_API_KEY` present but commented.
  - `agno` version **2.6.13**.
- Bott's source is **not** in this workspace. Decision (confirmed w/ user): rely on the brief's
  Bott description for now; only read Bott source later if/when we do review parity (#13).

### Decision: first step = isolation GO/NO-GO gate
Per brief constraint #4 / build-step #1. Confirmed with user over the alternative of reading Bott first.
Rationale: if Agno can't prove per-user no-bleed, the Agno bet is dead and any Bott reading is wasted.

### FINDING — Agno's isolation has TWO distinct layers (confirmed against live docs)
Source: docs.agno.com `/agent-os/security/authorization/user-isolation`, `/features/security-and-auth`,
`/sessions/persisting-sessions/overview`, `/use-cases/product-agents/sessions-and-memory`.

**Layer 1 — Data-model scoping (always on, but caller-trusted):**
- `user_id` distinguishes the person; `session_id` distinguishes a conversation thread.
- **Session history is scoped by `session_id`; memory is scoped by `user_id`** (across all that
  user's sessions). You pass both on every run.
- Works with any DB (incl. SQLite). BUT it only isolates if the *caller passes the correct ids* —
  the agent process is trusted. Nothing stops code from reading another user's rows by id.

**Layer 2 — Authorization enforcement (opt-in, this is the real guarantee):**
- `AgentOS(authorization=True, authorization_config=AuthorizationConfig(verification_keys=[...],
  algorithm="RS256", user_isolation=True))`.
- `user_id` is taken from the **JWT `sub` claim**, then **coerced on every read/write**:
  - No cross-user reads (other users' rows not returned).
  - No cross-user writes (`user_id` forced to caller's `sub`).
  - Cancel/resume/continue verify the run belongs to the caller's session.
- Admin scope (default `agent_os:admin`) **bypasses** isolation — sees everything.
- **Requires a DB that records `user_id` → PostgreSQL recommended for production.**

**Implication for current scaffold:** `workbench.py` (SQLite, no `user_id`, no authorization) has
**zero enforced isolation today** — everything is shared/unscoped. That's the starting point, not a bug.

### OPEN DESIGN QUESTION — the "engagement" axis is not native
The brief requires isolation on **two** dimensions: per-user AND per-engagement.
Agno gives exactly two native axes: `user_id` (→ memory) and `session_id` (→ thread).
There is **no native "engagement" scope**, and memory is strictly `user_id`-scoped — so a single user
working across two engagements would, by default, **share memory across both engagements**.
This must be modeled deliberately. Candidate approaches to evaluate in the gate (see task list).

### GATE RESULT — **GO** (13/13 hard assertions passed)
Artifact: `isolation_gate.py` (run: `.venv/bin/python isolation_gate.py`; exit 0 = GO).
Drives the **real HTTP routes** via FastAPI `TestClient` with per-user HS256 JWTs, against
`AgentOS(authorization=True, AuthorizationConfig(user_isolation=True))` on `SqliteDb`.

Proven:
- **Auth enforced:** no token → 401.
- **Core no-bleed:** alice lists only her sessions, bob only his; **bob is REFUSED alice's
  session by id (404)** even knowing the id; alice reads her own (200); **admin bypasses (200)**.
  (The negative/refusal case is exactly what Hermes profile-scoping reportedly can't enforce.)
- **Engagement model A (composite `user_id="<eng>::<person>"`):** same human on two engagements
  sees only the current engagement's session — engagement isolation rides on enforced
  user_isolation **for free**. Cost: one human = N subjects; personal cross-engagement memory
  must be stitched deliberately (separate `user_id`).
- **Engagement model B (memory=person, engagement via `session_id`):** threads separable by
  session, **but memory is shared across engagements by design** — right for a personal
  concierge, wrong when engagement context must not cross. Not enforced isolation.
- **Engagement model C (DB per engagement):** strongest (physical) separation — same user+id
  invisible across OS instances. Cost: heaviest infra, everything multiplied per engagement.

**Recommendation forming:** Model A for engagement-scoped agents (free enforced isolation),
Model B for the per-user concierge (personal memory should follow the person). Model C reserved
for hard client-data-segregation requirements. Revisit when wiring real agents.

Caveats / still owed:
- Run validated on **SqliteDb**; re-confirm on **Postgres** once Docker/disk is unblocked
  (Agno's production recommendation; mechanism is identical — route-level).
- Gate uses **HS256 shared secret** for convenience; production should use **RS256 + JWKS**.
- Benign teardown noise in stderr: OpenAI SDK's httpx client closing after the loop ends; cosmetic.

### Environment issue flagged to user
- **Disk at 99% full (~195 MB free on `/`)** → Docker daemon throws I/O errors and is unusable
  until space is freed. Worked around for the gate (SQLite, no Docker). Will block later steps
  (Docker Postgres, repo clones for review parity) until resolved.

### Effort so far
- Session 1: doc research + grounding + isolation gate build & green. One artifact
  (`isolation_gate.py`, ~230 lines) + this log. Deps added: `psycopg[binary]`, `pgvector`.
- Model spend: ~7 tiny `gpt-4o-mini` runs to create sessions. Negligible.

---

## 2026-06-15 — Session 2: PR code-review feature on Agno (Phase 1 of the mini-Bott)

Plan approved (see `~/.claude/plans/...babbage.md`). Scope: PR-review feature only, full
parity, model `gpt-4o-mini`, Slack-primary, phased (engine → Slack → GitHub App → UI).
Phase 1 = review engine + dry-run harness.

### Built — `review_poc/` package (faithful port of Bott `src/flows/review/`)
- `models.py` ← output-schema.ts (Pydantic `ReviewOutput`, used as Agno `output_schema`).
- `verdict_gate.py` ← verdict-gate.ts **verbatim** — all 10 preconditions, thresholds,
  downgrade/escalate/soft-note logic. **40/40 ported tests pass** (test_verdict_gate.py).
- `tools.py` ← tools.ts as an Agno `Toolkit` (read_file, get_file_diff, search_code,
  find_references, get_file_history, read_review_rules, get_ci_status, get_pr_comments,
  get_pr_description). Dropped `submit_review` (replaced by output_schema) + Jira (scope).
- `prompt.py` ← prompt.ts **v3.6** verbatim, submit_review framing swapped for output_schema.
- `github_client.py` (httpx REST), `fetch_essentials.py`, `noise.py`, `clone.py` (shallow
  clone w/ cross-fork fallback + context-manager cleanup), `diff_hunks.py` (anchor resolution),
  `render_github.py` ← render-github.ts, `runner.py` ← agent.ts, `pipeline.py` ← run.ts,
  `cli.py` (dry-run harness). Cost computed locally (config.MODEL_COSTS) — 43/43 tests pass.

### Agno API facts confirmed by introspection (v2.6.13)
- `agent.run()` → `RunOutput` with `.content` (typed when output_schema set), `.tools`
  (`ToolExecution.tool_name/tool_args/result`), `.metrics` (`input_tokens`, `output_tokens`,
  `cache_read_tokens`, `cost`), `.status`. `Agent(tool_call_limit=...)` caps tool calls.
- Custom tools via `Toolkit(tools=[self.method,...])`; `output_schema` + tool loop coexist.

### FIRST LIVE END-TO-END RUN — works. (pallets/click#3582, 3 files, +115/-6, CI=pass)
`python -m review_poc.cli <PR-URL>` → clone → agentic loop (real read_file/search_code/
find_references/get_file_history, all shown in "What I checked") → structured SUGGESTIONS
verdict (3 findings) → 10-row gate (claims_backed_by_tools PASS) → GitHub COMMENT render +
inline anchor resolution (1 anchorable, 2 body-fallback). Full pipeline green.

### FINDINGS (for the Hermes comparison)
- **Model discipline (gpt-4o-mini):** hit the 30-tool-call cap → `termination=budget`,
  **~1.15M input tokens**, ~**$0.17**/review for a 3-file PR. It churned instead of
  converging in the prompt's suggested 5–15 calls. Bott runs **Claude Sonnet**, which
  converges far faster. → real model-tier signal: cheap model ≠ cheap here; the agentic
  loop's growing context dominates cost. Tunable via `tool_call_limit` / model choice.
- **Cost not populated by Agno** for gpt-4o-mini (`metrics.cost=None`) — we compute it
  ourselves. (Matches the Anthropic caveat noted earlier; applies to OpenAI here too.)
- **Gate fidelity holds** on real output: the budget termination correctly flunked
  `natural_termination`; verdict stayed SUGGESTIONS (no APPROVE to downgrade).

- **Budget sensitivity (same PR, two caps) — important:**
  - `tool_call_limit=30`: 30 calls, **1.15M tok**, ~$0.17, `termination=budget`, verdict
    SUGGESTIONS (3 findings).
  - `tool_call_limit=15`: 11 calls, **52k tok**, **$0.0047**, `termination=natural`, verdict
    APPROVE (0 findings).
  → gpt-4o-mini expands to fill the budget; the cap drives **both cost (≈22×) and the verdict**.
  Cleaner+cheaper at 15, but shallower (found nothing). Neither clearly matches Bott/Sonnet
  depth. Cost reporting now works (computed locally). Tunable knob for the cost/quality axis.

### Phase 1 status: DONE
Review engine + dry-run harness ported faithfully and green end-to-end on a real PR.
43/43 unit tests (40 gate parity + 3 cost). Pending user inputs gate later phases (Slack
tokens; Bott-POC GitHub App + test repo).

### Effort
- Session 2: ~14 module port + 43 tests, 2 live PR runs (~$0.18 total). Deps added: `pytest`.

---

## 2026-06-15 — Session 4: Phase 3 — GitHub App + webhook (auto-trigger + posting)

### Built (code complete, locally verified)
- `review_poc/github_app.py`: App ID + private key → app JWT (RS256) → per-installation
  access token (cached ~55m). Authenticates clone + reads + posting as the App (5000/hr).
- `app/webhook.py` (FastAPI): HMAC-SHA256 verify, `pull_request` opened/ready_for_review →
  enqueue review (source=github), dedup on X-GitHub-Delivery, skip drafts/bots/other actions.
  Verified offline: bad-sig→401, ping→200, opened→enqueue, dup→skip, draft/bot/closed→skip.
- `review_poc/store.py`: `github_deliveries` dedup table + `recover_orphans`; all fns now
  resolve `DB_FILE` dynamically (testability).
- `app/slack_app.py handle_task`: webhook-sourced reviews mint an App token, post the review
  to the PR (allowlist-guarded via `ALLOWED_POST_REPOS`), and mirror to Slack if
  `REVIEW_SLACK_CHANNEL` set (Slack output optional; checklist/posting guarded on channel).
- `app/server.py`: unified entrypoint — Slack Socket Mode (main thread) + FastAPI webhook
  (uvicorn daemon thread) + shared worker, one process so the worker posts to both surfaces.
- Deps: `pyjwt[crypto]`, `cryptography`, `uvicorn`. Tunnel: `cloudflared` (quick tunnel →
  localhost:8085). Slack `online` dot = App Home "Always Show My Bot as Online" toggle.

### Phase 3 — DONE (verified end-to-end)
User created Bott-POC GitHub App (id 4061609) + test repo `Pulkit0111/bott-pr-review-harness`,
installed it. Config wired in `.env`; App auth verified (installation token → repo 200).
**Live proof (PR #3, SQL-injection bug seeded via the harness repo's own scenario script):**
webhook → queued → reviewed → App `bott-poc-reviewer[bot]` posted **CHANGES_REQUESTED** on the
PR with an inline `[ISSUE · Security]` comment at `users.py:15`, AND mirrored "⛔ Issues found"
to the Slack channel. Allowlist held (posts only to the test repo). Correct blocking verdict on
a real bug — the headline parity behavior.

Note: `/Users/pulkittyagi/Desktop/bott-harness` is a purpose-built review-test harness with ~24
seeded scenarios (`scripts/test-scenario.sh <key>`) — ideal for a batch parity/quality run.

### Auto-review Slack format fix (matches Bott)
Webhook reviews now post a parent announcement ("🔍 Auto-reviewing `owner/repo`#N: <title> —
by <author>") with the review as a threaded reply (was posting the review top-level). Webhook
passes title+author; re-review continuity keyed to the announcement thread. Verified live on PR #3.

### Phases 1–3 complete. Remaining: Phase 4 (agent-ui management).

---

## 2026-06-15 — Session 5: production hardening + cleanup

Goal: make the Slack-primary PR reviewer production-robust and remove cruft (keep BUILD_LOG).

### Cleanup
Removed stale scaffolding/artifacts: `workbench.py`/`workbench.db` (hello-world), `isolation_gate.py`
+ `iso_*.db` (Phase-0 proof; findings retained here), all `__pycache__`, `.pytest_cache`, `*.log`.
Kept `agent-ui/` (Phase 4, user's call), `BUILD_LOG.md`, runtime `review_poc.db`.

### Hardening (all in)
- **Logging + secret redaction** (`review_poc/logging_setup.py`): structured logging; a filter
  scrubs GitHub installation tokens in clone URLs (`x-access-token:***@`), `gh*_`/`xox*`/`sk-`
  tokens from every log line. Verified: no secrets in logs after a live run.
- **Fail-fast config validation** at startup (`config.validate_required`): clear errors for
  missing OpenAI/Slack tokens; warns (not fatal) when the GitHub App isn't configured.
- **Retries**: GitHub client retries 429/5xx/403-rate-limit with backoff; worker retries
  transient task failures up to 3 attempts (new `attempts` column) before failing.
- **Graceful shutdown** (SIGTERM/SIGINT → stop worker + close Slack handler) and **stale-clone
  sweep** on boot (reclaimed 1 leaked dir on first run).
- **Config-driven** model + budgets via env (`REVIEW_MODEL`, `REVIEW_MAX_TOOL_CALLS/TOKENS/USD`).
- **Hygiene**: `.gitignore` (`.env`, `*.pem`, `*.db`, venv, caches) + pinned `requirements.txt`.
- **Tests**: 70 passing (was 43) — added webhook (sig/dedup/skips/enqueue), store
  (queue/retry/orphans/dedup/trace), render_slack, diff_hunks, intake, redaction.

### How to run
`uv pip install -r requirements.txt` → set `.env` → `.venv/bin/python -m app.server`
(Slack + webhook + worker, one process). Webhook needs the cloudflared tunnel for GitHub delivery.

### Status: Phases 1–3 production-hardened + verified (live smoke green, 70 tests). Phase 4 next.

---

## 2026-06-15 — Session 3: Phase 2 — Slack as primary interface

User provided Bott-POC Slack app tokens (Socket Mode). Stored in `.env`
(`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`) — not committed (not a git repo). Dep: `slack-bolt`.

### Built
- `review_poc/render_slack.py` ← render-slack.ts: verdict header + summary + verdict-changed
  block (re-reviews) + counts + top-3 findings + "what I checked" + soft-note/downgrade footer
  + buttons (View on GitHub, Re-review). Apply-fixes button deferred.
- `review_poc/store.py`: SQLite task queue + review traces + thread index + a background
  `Worker` thread (mirrors Bott queue->worker->dispatch).
- `review_poc/rereview.py`: prior-review text builder + issue-finding extraction for the gate.
- `app/slack_app.py`: Socket-Mode Bolt app. `@bott-poc review <PR-URL>` → :eyes: → enqueue →
  worker runs the Phase-1 engine → threaded verdict; reaction swapped to verdict emoji.
  Thread replies (or @mention in-thread, or the Re-review button) → evidence-bound re-review
  (prior verdict + findings fed to the gate; reply captured as answer-context).
  Review budget capped at 15 tool calls (Phase-1 cost finding).

### Fix worth noting
- python.org Python build has no CA certs; `slack_sdk` uses urllib (not httpx) → SSL verify
  failed. Fixed by pointing `SSL_CERT_FILE`/`SSL_CERT_DIR` at `certifi.where()` at app startup.

### Status: bot LIVE
Connects via Socket Mode ("⚡️ Bolt app is running!", bot user U0BAS5SEFBN), worker polling.
Offline smoke tests pass (store enqueue/dequeue, Slack blocks json-serializable).

### First live Slack test surfaced 3 issues — all fixed
Read the actual thread via the bot token (the `claude_ai` Slack MCP is on a different
workspace, so `channel_not_found`). Findings + fixes:

1. **Raw failure message leaked internals** — user saw `Review failed — termination=no_submission`.
   Fixed: `_friendly_failure()` maps reasons to human text ("I hit the model's per-minute rate
   limit… tag me again"); technical detail logged server-side only.
2. **Command-driven, not conversational** — "Re-review this PR" fell back to a `review <URL>`
   help string. Fixed: new `review_poc/intake.py` — an LLM intake layer interprets each message
   (review / rereview / chat), extracts the PR ref, and writes a warm 1–2 sentence reply.
   Slack handlers now route everything through `_converse()`; in-thread chat is grounded with the
   prior review summary. Verified: "what do you do?"→chat, "take a look at <url>"→review,
   "check CSRF again"→rereview.
3. **OpenAI 200k TPM rate limit kept failing reviews** — gpt-4o-mini's agentic loop is
   context-hungry (~1.15M tokens/run, repeatedly saturating 200k tokens/min even with retries).
   **Root fix = model swap to `gpt-4.1-mini`** (1M context, faster). Also added model retries
   + leaner loop (12 tool calls, 250-line read cap).

### MODEL FINDING (big one for the comparison)
Same PR (pallets/click#3582), same engine, just the model:
| model | tool calls | tokens | time | termination | cost |
|---|---|---|---|---|---|
| gpt-4o-mini | 15 (cap) | **4.4M** | minutes (w/ retries) | budget | **$0.34** |
| **gpt-4.1-mini** | **5** | **13.4k** | **14s** | **natural** | **$0.0026** |
→ gpt-4.1-mini is ~330× fewer tokens, ~130× cheaper, far faster, and reliable. The "cheap" model
(4o-mini) was actually the expensive, unreliable one here — it never converges and balloons
context. Model choice dominates both reliability and cost on the agentic loop. Default is now
`gpt-4.1-mini` (override via `REVIEW_MODEL`).

### Phase 2 — DONE (user verified end-to-end in Slack)
Conversational, single evolving message per review, Bott-style stage checklist
(✅ done · ⏳ now · ⚪ pending) with the live "3 reads · 1 search · review rules" tally,
graceful failures (rate-limit/fetch errors → friendly message, never stuck), orphan recovery.
Note: "Always Show My Bot as Online" is a Slack app-config toggle (App Home), not code.
Note: GitHub's 60/hr unauthenticated limit throttles reviews — a `GITHUB_TOKEN` (5000/hr) is
the fix and is needed for Phase 3 anyway.

---

## REFERENCE: POC vs the real Bott PR review (saved for later)

### The flow (identical shape — the POC is a faithful port of Bott's design)
1. **Trigger** — GitHub App webhook (PR opened/ready) OR Slack message OR re-review.
2. **Fetch essentials** — PR title/body, diff, changed files, CI status, comments (GitHub API).
3. **Runtime shallow clone** at the PR's exact head SHA into a temp dir. Nothing pre-indexed.
4. **Agentic tool loop** — agent forms hypotheses (security/correctness/tests/conventions/ops)
   and verifies with tools: read_file, get_file_diff, search_code (ripgrep), find_references,
   get_file_history, read_review_rules, get_ci_status, get_pr_comments, get_pr_description.
5. **Structured verdict** — approve | suggestions | issues + line_comments (severity/category/
   action/optional suggested_change) + confidence + (re-review) withdrawn_findings.
6. **Verdict gate (10 preconditions)** — earns/downgrades/escalates the verdict; the quality core.
7. **Render + post** — GitHub review (body + inline comments) and/or Slack; clone deleted;
   only a trace (verdict + gate decisions) persisted.

### Same as Bott (deliberately ported, near 1:1)
- Pipeline shape; runtime-clone-then-delete (no code storage).
- Tool set (the ~9 review tools).
- **v3.6 system prompt** (voice, hypothesis checklist, evidence-required rules).
- **Structured output schema** (output-schema.ts → Pydantic).
- **10-precondition verdict gate** (verdict-gate.ts ported near-verbatim; 40 ported tests pass).
- GitHub App + webhook + Slack surfaces; re-review with evidence-bound withdrawals;
  auto-review announcement-parent + threaded review in Slack.

### Different (POC vs production Bott)
| Dimension | POC (this repo) | Real Bott |
|---|---|---|
| **Model** | `gpt-4.1-mini` (cheap/fast) | **Claude Sonnet** on Amazon Bedrock (stronger reasoning) |
| **Agent loop** | Agno `Agent` (output_schema + tools) | `pi-agent-core` (terminal `submit_review` tool) |
| **Queue / DB** | SQLite + single worker thread | **Postgres** queue + worker (mature, idempotent) |
| **Deployment** | local machine + cloudflared tunnel | EC2 + Docker + CI/CD (production) |
| **Trace store** | SQLite (verdict + gate decisions) | Postgres `pulse_review_traces` (full trace, analytics) |
| **NOT built in POC** | review only | **Apply-fixes** (commits suggestions), **Jira** ticket grounding, **stack profiles** (Drupal/Magento/etc. conventions), multi-project/tenant config, cost/audit dashboards, status-check posting |
| **Budget enforcement** | `tool_call_limit` + post-hoc cost calc | mid-loop token/USD/tool-call budget (consumeToolCall) |
| **Idempotency** | dedup on webhook delivery id + worker retries | per-tool `withIdempotency` cache + dup-review skip |

### Bottom line
The *brains* — prompt, tools, structured output, and the 10-rule verdict gate — are a faithful
port, so review **behavior** is close to Bott's. The two real gaps are: (1) **model tier**
(gpt-4.1-mini vs Claude Sonnet — expect a quality gap on hard/large PRs), and (2) **scope** —
the POC intentionally omits Apply-fixes, Jira grounding, stack profiles, and the full
production substrate (Postgres, EC2/CI/CD, dashboards). Quality findings on the model axis:
gpt-4.1-mini reviewed a real PR in 5 tool calls / 13k tokens / 14s / $0.0026 and correctly
blocked a seeded SQL-injection PR (CHANGES_REQUESTED) — see Sessions 2–4 above.
