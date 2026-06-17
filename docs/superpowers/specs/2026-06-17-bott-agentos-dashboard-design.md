# Bott AgentOS Dashboard — Design (Milestone 1)

**Date:** 2026-06-17
**Status:** Approved for planning
**Topic:** A custom, self-hosted control-plane UI for Bott, backed by a unified AgentOS that
Slack and the dashboard both share.

## Summary

Bott today is a Slack-first Agno `Team` (a conversational manager that delegates to a
code-review specialist), plus a GitHub webhook and a durable worker. There is no HTTP
control-plane API and no dashboard. The existing `agent-ui/` is the official Agno Next.js
starter — chat-only — whose API helpers already expect an AgentOS backend that does not yet
exist.

This milestone:

1. **Wraps Bott in a unified AgentOS** so it serves the standard AgentOS REST API
   (`/config`, `/agents`, `/teams`, `/sessions`, `/runs`, `/metrics`, `/health`).
2. **Unifies state across Slack and the dashboard** by giving the manager team + code-review
   agent a single shared Agno `SqliteDb`. Slack threads become persistent Agno sessions, so
   they appear in the dashboard's Sessions list and count toward Metrics.
3. **Builds a custom route-based dashboard UI** (extending `agent-ui`): a persistent sidebar
   shell, a Home dashboard of real agent/team/workflow cards, a full Sessions page, and the
   existing Chat moved under its own route.

The existing Slack server keeps running. The dashboard is a second front door into the same
Bott, not a replacement.

## Decisions (from brainstorming)

- **Data source:** wrap Bott in a real AgentOS (not mock data).
- **UI:** build our own custom UI (not the official `os.agno.com` control plane), starting
  minimal — shell + Home + Chat (reuse) + Sessions for M1.
- **Home content:** honest — render only what exists (1 team, 1 agent, 0 workflows). The grid
  grows automatically as real components are added.
- **Slack:** stays. Runs alongside the dashboard.
- **Shared state:** unified — Slack conversations show up as sessions/metrics in the UI via a
  shared Agno db.

## Non-Goals (M1)

- Traces, Studio editors (create/edit agents in-UI), Learning, Memory, Knowledge, Metrics
  charts, Evaluation, Approvals/HITL, Scheduler. Each is a later milestone that adds one route
  segment against an already-existing AgentOS endpoint.
- Replacing Bott's custom Slack app with Agno's generic Slack interface. Bott's Slack layer
  (Socket Mode + webhook + worker + personality + mrkdwn rendering) is kept as-is.
- Authn/RBAC beyond the existing bearer-token (`OS_SECURITY_KEY`) the UI already supports.

## Architecture

Two front doors, one brain, one store:

```
                 ┌─────────────────────────────┐
   Slack  ─────▶ │  shared manager Team +       │
   (Socket Mode) │  code-review Agent           │ ──▶  shared SqliteDb (agentos.db)
   GitHub webhook│  (single definition, one db) │       sessions · metrics · memory
   Dashboard ──▶ │                              │
   (HTTP/AgentOS)└─────────────────────────────┘
```

- The team/agent definition lives in **one factory** (B1). State is shared via the **db file**,
  not a shared in-memory object.
- Process model: the existing `server.py` is untouched; a new `agentos-server` entrypoint serves
  HTTP. They are **separate processes**, each constructing its own team instance from the same
  factory and pointing at the same `agentos.db`. Shared state = shared db, not shared object.
  SQLite WAL mode handles concurrent readers + the low write volume here.

## Backend Design

### B1. Shared team factory (refactor)

`src/bott/manager/manager.py` — `build_manager` currently builds a fresh `Team` per Slack
message, closing Slack context into the code-review tools, with no db.

Refactor to:

- Build the manager `Team` + code-review `Agent` **once** with a shared Agno `SqliteDb`
  (`agentos.db`). Expose a module-level accessor (e.g. `get_manager()` / `get_code_review_agent()`)
  used by both the Slack handler and the AgentOS wrapper.
- Move Slack post-target context (channel, `thread_ts`) out of tool closures and into
  **per-run `dependencies`** passed at `team.run(...)` time. The code-review tools read the
  post-target from dependencies when present.
- Keep `personality.py` (IDENTITY / VOICE / NAME), `shared/model.py`, and `shared/config.py`
  as the single sources of voice/model/config.

### B2. Code-review agent — context-free, dependency-driven

`src/bott/agents/code_review/member.py` — `make_review_tools(ctx)` closes over `SlackContext`.

Refactor so `start_review` / `start_rereview`:

- Read the Slack post-target (channel, thread_ts) and the `enqueued` flag from run
  dependencies / session state rather than a closure.
- When invoked from a Slack run: enqueue to the shared worker store exactly as today (no
  behavior change for Slack users).
- When invoked from a UI run (no Slack target): enqueue without a Slack post-target and reply
  in-chat with queued status. (Posting UI-initiated review results back into the UI is a later
  milestone; M1 only needs the queue + status.)

### B3. AgentOS wrapper (new)

`src/bott/interfaces/agentos.py`:

- Import the shared team + agent from B1.
- Construct `AgentOS(agents=[code_review_agent], teams=[manager_team], db=sqlite_db)` and
  `app = agent_os.get_app()`.
- New console script `agentos-server` in `pyproject.toml` (`agno`'s `serve` on port 7777 — the
  UI's default `selectedEndpoint`).
- Respect the existing `OS_SECURITY_KEY` bearer token if set (the UI already sends
  `Authorization: Bearer …`).
- Workflows list is empty (Bott has none) — honest.

### B4. Slack handler — session-bound runs

`src/bott/interfaces/slack_app.py`:

- Use the shared team from B1 (built once at startup) instead of rebuilding per message.
- Derive a stable `session_id = "slack:{channel}:{thread_ts}"` and `user_id` from the Slack
  user, and run `team.run(text, session_id=..., user_id=..., dependencies={slack post-target})`.
- Net effect: each Slack thread is one persistent Agno session (improved memory across the
  thread) and is visible in the dashboard.

### B5. Backend test

A lightweight pytest (consistent with the existing suite) that imports `agentos.py`, builds the
app with a temp db, and asserts `/health` and `/agents` respond and list the real agent/team.

## Frontend Design

### F1. Route-based shell (restructure of `agent-ui`)

App Router segments under a shared dashboard layout:

```
src/app/
  layout.tsx                 # root: theme, fonts, Suspense (existing; minimal change)
  (dashboard)/
    layout.tsx               # NEW: AppShell — Sidebar + TopBar + {children}
    page.tsx                 # NEW: Home dashboard  (route: /)
    chat/page.tsx            # Chat — renders existing <ChatArea/> (moved, not rewritten)
    sessions/page.tsx        # NEW: full-page Sessions list
```

- **`components/layout/Sidebar`**: Agno logo, nav items with `lucide-react` icons, a
  collapsible "Studio" group, user footer. Lists all 13 eventual destinations; M1-live routes
  (Home, Chat, Sessions) navigate, the rest render a shared `<ComingSoon/>` placeholder so the
  nav matches the reference without faking data.
- **`components/layout/TopBar`**: OS name + health dot (from `/health`), a Refresh action, and a
  Settings popover holding endpoint + auth-token config (reusing the existing `AuthToken` and
  endpoint logic, relocated from the old chat sidebar).
- The existing chat `Sidebar` is demoted: its endpoint/entity/mode selectors move into the chat
  page and the Settings popover; its session-list logic is reused by the Sessions page. Chat
  *behavior* is unchanged.

### F2. Home dashboard (`/`)

- On mount, fetch `/config` (and/or `/agents` + `/teams`) via existing `getAgentsAPI` /
  `getTeamsAPI`, using `selectedEndpoint` + `authToken` from the Zustand store.
- Render grouped sections — `AGENTS`, `TEAMS`, `WORKFLOWS` — each a responsive grid of
  `EntityCard`s (icon, name, description, capability/model tags, `CHAT` + `CONFIG` actions).
  - `CHAT` → `/chat?type={agent|team}&id=…` preselecting that entity.
  - `CONFIG` → a read-only config drawer (M1) showing model / db / tools from the entity detail.
- Empty groups show an empty-state ("No workflows yet"). Collapsible group headers.
- Loading: skeleton cards. Endpoint-down: inline banner + Retry (reuse `isEndpointActive`).

### F3. Sessions page (`/sessions`)

Full-page version of the existing sidebar session list. Reuses `getAllSessionsAPI`, the
`SessionItem` / `DeleteSessionModal` components, the agent/team toggle, and the delete flow.
Clicking a session opens it in `/chat`. A small "source" badge (slack / web) is derived from the
`session_id` prefix. Pure reuse + relayout — no new data logic.

### F4. State & data flow

- Keep the existing Zustand `useStore` (endpoint, authToken, agents, teams, mode, sessions).
  Add `osConfig` (name, available models) + `setOsConfig`, populated from `/config`.
- Use `nuqs` (already a dependency) for URL query state (`?type`, `?id`, `?session`) so Chat and
  Sessions deep-link.

### F5. Theming, errors, testing

- **Theming:** reuse the existing dark theme + orange accent and the shadcn/Radix primitives
  already in `agent-ui` — visually consistent with the reference out of the box.
- **Errors:** endpoint-down banner; per-section fetch failures toast via the existing `sonner`
  setup; placeholders never crash on empty data.
- **Testing:** `agent-ui` has no test runner today, so M1 frontend verification = `pnpm validate`
  (lint + prettier + typecheck) passing, plus a manual run against the live `agentos-server`:
  Home lists the real team + agent, Chat talks to the manager, Sessions persist and show both
  web- and Slack-originated sessions.

## Sequencing (de-risking the unified refactor)

Because this modifies a working production Slack flow, M1 ships in two independently
verifiable phases:

- **Phase 1 — Backend.** B1–B5: shared team-with-db refactor + dependency-driven review tools +
  AgentOS wrapper + Slack session binding. **Gate:** the existing Slack flow still behaves
  identically (queue a review → get the verdict), AND sessions now persist in `agentos.db`, AND
  `/agents` + `/health` respond. No UI changes yet.
- **Phase 2 — Frontend.** F1–F5: shell + Home + Chat + Sessions against the Phase-1 AgentOS.
  **Gate:** `pnpm validate` passes and the manual run checklist above passes.

## Risks

- **Touching the working Slack path** (B1, B2, B4). Mitigated by Phase-1 behavioral gate before
  any UI work, and by keeping Bott's Slack layer/personality/rendering intact — only the team
  construction and run-invocation change.
- **Concurrent SQLite access** from two processes. Mitigated by WAL mode and Bott's low write
  volume; revisit if contention appears.
- **Review tools' Slack-context decoupling** could regress Slack posting if dependencies aren't
  threaded correctly. Covered by the Phase-1 gate (a real queued review must still post).

## Out of scope / future milestones

Traces · Studio (in-UI agent/team/workflow editors) · Learning · Memory · Knowledge ·
Metrics charts · Evaluation · Approvals/HITL · Scheduler · posting UI-initiated review results
back into the dashboard chat. Each is a later route segment against an existing AgentOS endpoint.
