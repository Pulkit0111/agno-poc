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
4. **Gates everything behind Google sign-in restricted to `axelerant.com`.** Nothing in the
   dashboard (Home, config, chat, sessions) renders for an unauthenticated user, and the
   AgentOS API itself rejects any request that isn't carrying a token minted for a verified
   `axelerant.com` identity.

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
- **Auth:** Google OAuth via Auth.js (NextAuth v5), restricted to `axelerant.com` accounts.
  Gate depth = **UI + API** (defense in depth): the browser never talks to AgentOS directly and
  never holds a static admin key; AgentOS validates a per-request JWT minted by our server.
- **Session visibility:** all authenticated `axelerant.com` users see all sessions/metrics
  (shared internal control plane). AgentOS `user_isolation` stays **off** — required for the
  unified view, since Slack sessions are owned by Slack users, not the web user. Easily flipped
  later if per-user isolation is wanted.

## Non-Goals (M1)

- Traces, Studio editors (create/edit agents in-UI), Learning, Memory, Knowledge, Metrics
  charts, Evaluation, Approvals/HITL, Scheduler. Each is a later milestone that adds one route
  segment against an already-existing AgentOS endpoint.
- Replacing Bott's custom Slack app with Agno's generic Slack interface. Bott's Slack layer
  (Socket Mode + webhook + worker + personality + mrkdwn rendering) is kept as-is.
- Multi-tenant RBAC / per-resource scopes / per-user data isolation. M1 auth is binary:
  a verified `axelerant.com` user is fully in; everyone else is fully out.
- Non-Google identity providers, multiple allowed domains, or an allow-list of individual
  emails. Single hardcoded-via-env domain (`axelerant.com`) only.

## Architecture

Two front doors, one brain, one store — with the dashboard door gated by Google auth:

```
  Browser ──▶ Next.js app ──────────────┐
   (Google   (Auth.js gate: axelerant   │  mints short-lived
    sign-in)  domain; BFF proxy routes)  │  HS256 JWT per request
                                         ▼
                 ┌─────────────────────────────┐
   Slack  ─────▶ │  shared manager Team +       │   JWTMiddleware validates the
   (Socket Mode) │  code-review Agent           │   token (shared secret) before
   GitHub webhook│  (single definition, one db) │ ──▶  shared SqliteDb (agentos.db)
                 │                              │       sessions · metrics · memory
   (HTTP/AgentOS)└─────────────────────────────┘
```

- The team/agent definition lives in **one factory** (B1). State is shared via the **db file**,
  not a shared in-memory object.
- Process model: the existing `server.py` is untouched; a new `agentos-server` entrypoint serves
  HTTP. They are **separate processes**, each constructing its own team instance from the same
  factory and pointing at the same `agentos.db`. Shared state = shared db, not shared object.
  SQLite WAL mode handles concurrent readers + the low write volume here.
- The browser only ever talks to the Next.js server. The Next.js server is the only thing that
  talks to AgentOS, and it is the only holder of the JWT signing secret. (Slack does not pass
  through the HTTP/JWT layer — it's a separate process writing to the same db.)

## Authentication & Authorization

### A1. Frontend gate — Auth.js (NextAuth v5) + Google

- Add Auth.js to the Next.js app with the **Google provider**. Session strategy: **JWT** (no
  extra db).
- `signIn` callback **rejects** unless the Google profile has `email_verified === true`, the
  Workspace **`hd` (hosted-domain) claim === `axelerant.com`**, AND the email ends with
  `@axelerant.com`. Checking `hd` (not just the email string) is what makes this spoof-resistant
  — `hd` is only present and trustworthy on Google Workspace accounts. The allowed domain comes
  from an env var (`ALLOWED_EMAIL_DOMAIN=axelerant.com`).
- `middleware.ts` protects **every** route except the public sign-in page and the Auth.js
  endpoints. Unauthenticated → redirect to `/sign-in`.
- A public **`/sign-in`** page: a single "Sign in with Google" button, plus a clear
  "access is restricted to axelerant.com accounts" message and a friendly rejected-user state
  for anyone who passes Google but fails the domain check.

### A2. Backend-for-frontend (BFF) proxy + minted token

- The browser **no longer calls AgentOS directly**. All API/SSE traffic goes through Next.js
  route handlers under `src/app/api/os/[...path]/route.ts`, which:
  1. Load the Auth.js session server-side; reject (401) if absent or non-`axelerant.com`.
  2. **Mint a short-lived HS256 JWT** signed with a shared secret (`AGENT_OS_JWT_SECRET`), with
     claims `{ sub: email, email, name, hd, iat, exp(~5 min) }`.
  3. Forward the request to the real `AGENT_OS_URL` (server-side env) with
     `Authorization: Bearer <minted JWT>`, **streaming** the upstream response body straight
     back to the browser (preserving the chat SSE stream).
- Rationale for minting our own token (vs forwarding Google's `id_token`): decouples from
  Google token lifetime/refresh, keeps a stable `sub` (the email) for session ownership, and
  needs only a shared secret rather than wiring AgentOS to Google's JWKS.

### A3. AgentOS-side validation — `JWTMiddleware`

- In `agentos.py`, add Agno's `JWTMiddleware` (natively supported): `algorithm="HS256"`,
  `verification_keys=[AGENT_OS_JWT_SECRET]`, `validate=True`, `user_id_claim="sub"`,
  `dependencies_claims=["email", "name", "hd"]`, and `excluded_route_paths` left at the default
  public set (`/health`, `/docs`, `/openapi.json`, …).
- Because only the BFF holds the signing secret and the BFF only mints tokens for verified
  `axelerant.com` users, a valid token **implies** an authorized user — the domain restriction
  is enforced end to end. A small assertion that the `hd`/`email` claim matches
  `ALLOWED_EMAIL_DOMAIN` is added as belt-and-suspenders.
- `user_isolation=False` (see Decisions): all authenticated users share the same view, so
  Slack-originated sessions remain visible alongside web sessions.

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
  UI's default endpoint, now reached only via the Next.js BFF, not the browser).
- Add `JWTMiddleware` for authentication (see A3). Bound to localhost / private network; the
  only legitimate caller is the Next.js server.
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
- **`components/layout/TopBar`**: OS name + health dot (from `/health`) and a Refresh action.
  The endpoint is now server-configured (`AGENT_OS_URL`) and the token is minted server-side, so
  the old user-editable endpoint/auth-token settings are **removed** — there's nothing for the
  user to configure and no secret to expose.
- **Sidebar user footer**: shows the signed-in Google profile (name, avatar, email) and a
  **Sign out** action, replacing the static mock user. Sign-out clears the Auth.js session.
- The existing chat `Sidebar` is demoted: its entity/mode selectors move into the chat page; its
  session-list logic is reused by the Sessions page. Its endpoint/auth-token inputs are dropped
  (handled by auth + server config now). Chat *behavior* is unchanged.

### F2. Home dashboard (`/`)

- On mount, fetch `/config` (and/or `/agents` + `/teams`) via existing `getAgentsAPI` /
  `getTeamsAPI`, **repointed at the relative `/api/os/...` BFF proxy** (A2) instead of a
  user-supplied endpoint. No bearer token is handled client-side.
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

- Keep the existing Zustand `useStore` (agents, teams, mode, sessions). The `selectedEndpoint`
  and `authToken` fields are retired in favor of the fixed `/api/os` proxy base + server-side
  token. Add `osConfig` (name, available models) + `setOsConfig`, populated from `/config`, and
  `user` (name/email/avatar) from the Auth.js session.
- All API helpers (`api/os.ts`, `api/routes.ts`) and the streaming hook target the relative
  `/api/os/...` BFF base rather than an absolute AgentOS URL.
- Use `nuqs` (already a dependency) for URL query state (`?type`, `?id`, `?session`) so Chat and
  Sessions deep-link.

### Environment / config additions

- **Frontend (`agent-ui`):** `AUTH_SECRET`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, `AUTH_URL`,
  `ALLOWED_EMAIL_DOMAIN=axelerant.com`, `AGENT_OS_URL` (server-side real AgentOS),
  `AGENT_OS_JWT_SECRET` (shared with backend).
- **Backend:** `AGENT_OS_JWT_SECRET` (same value), `ALLOWED_EMAIL_DOMAIN`. Documented in
  `.env.example`.

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

Because this modifies a working production Slack flow, M1 ships in three independently
verifiable phases:

- **Phase 1 — Backend core.** B1–B5: shared team-with-db refactor + dependency-driven review
  tools + AgentOS wrapper + Slack session binding. **Gate:** the existing Slack flow still
  behaves identically (queue a review → get the verdict), AND sessions now persist in
  `agentos.db`, AND `/agents` + `/health` respond. No UI, no auth yet.
- **Phase 2 — Auth pipe.** A1–A3: Auth.js Google gate (axelerant-only) + `/sign-in` page + BFF
  proxy + AgentOS `JWTMiddleware`. Build against a single throwaway protected page. **Gate:** a
  non-axelerant Google account is rejected; an axelerant account reaches a protected page; a
  direct `curl` to AgentOS without a valid minted token is 401; the BFF proxies a real
  `/agents` call successfully.
- **Phase 3 — Dashboard UI.** F1–F5: shell + Home + Chat + Sessions behind the Phase-2 gate.
  **Gate:** `pnpm validate` passes and the manual run checklist passes — Home lists the real
  team+agent, Chat streams through the proxy, Sessions show both web- and Slack-originated rows.

## Risks

- **Touching the working Slack path** (B1, B2, B4). Mitigated by Phase-1 behavioral gate before
  any UI work, and by keeping Bott's Slack layer/personality/rendering intact — only the team
  construction and run-invocation change.
- **Concurrent SQLite access** from two processes. Mitigated by WAL mode and Bott's low write
  volume; revisit if contention appears.
- **Review tools' Slack-context decoupling** could regress Slack posting if dependencies aren't
  threaded correctly. Covered by the Phase-1 gate (a real queued review must still post).
- **Streaming through the BFF proxy.** Chat is SSE; the Next.js route handler must stream the
  upstream body rather than buffer it. Verified in the Phase-3 gate (Chat must stream, not
  arrive all-at-once). Known-doable with App Router route handlers returning the upstream
  `ReadableStream`.
- **JWT secret management.** `AGENT_OS_JWT_SECRET` must match on both sides and never reach the
  browser. Kept server-side only (BFF + AgentOS); documented in `.env.example` with a note to
  use a strong (256-bit+) value.
- **`hd`-claim assumption.** The domain gate trusts Google's `hd` claim, which is only reliable
  for Workspace accounts. Personal Gmail accounts lack `hd` and are rejected — intended, since
  axelerant.com is a Workspace domain.

## Out of scope / future milestones

Traces · Studio (in-UI agent/team/workflow editors) · Learning · Memory · Knowledge ·
Metrics charts · Evaluation · Approvals/HITL · Scheduler · posting UI-initiated review results
back into the dashboard chat. Each is a later route segment against an existing AgentOS endpoint.
