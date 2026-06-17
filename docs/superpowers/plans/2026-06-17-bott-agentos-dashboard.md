# Bott AgentOS Dashboard — Implementation Plan (Milestone 1)

**Goal:** Wrap Bott in a unified AgentOS (shared with Slack via one SQLite db), gate it behind Google sign-in restricted to `axelerant.com`, and build a custom route-based dashboard (shell + Home + Chat + Sessions) in `agent-ui`.

**Spec:** `docs/superpowers/specs/2026-06-17-bott-agentos-dashboard-design.md`

**Architecture:** Two processes share one Agno `SqliteDb` (`agentos.db`). The existing Slack server is untouched behaviorally; a new `agentos-server` serves the AgentOS REST API. The Next.js app authenticates via Auth.js (Google, axelerant-only) and proxies all API/SSE traffic through a server-side BFF that mints a short-lived HS256 JWT; AgentOS's `JWTMiddleware` validates it.

**Tech Stack:** Python 3.10+, Agno 2.6.13, FastAPI/uvicorn (backend) · Next.js 15 App Router, React 18, Auth.js (NextAuth v5), jose, Zustand, Tailwind, Radix/shadcn (frontend).

**Ground rules:** Conventional commits, commit after each task. Backend tests with `pytest`. Frontend gate is `pnpm validate` (lint + prettier + typecheck) plus the manual run checklist. Work on a branch (`feat/agentos-dashboard`), not `main`.

---

## Phase 1 — Backend core (no UI, no auth)

**Outcome:** `agentos-server` serves `/health`, `/agents`, `/teams`, `/sessions` with the real Bott manager team + code-review agent, persisting to `agentos.db`. Slack still behaves identically, and Slack threads now persist as Agno sessions.

**Phase gate (must all pass before Phase 2):**
1. `pytest` green (existing suite + new tests).
2. Manual: start the Slack server, queue a review (`@bott review <PR>`) → verdict still posts in-thread; reply in-thread → re-review still works.
3. Manual: start `agentos-server`, `curl localhost:7777/health` → ok; `curl localhost:7777/agents` → lists `code-review`; `curl localhost:7777/teams` → lists `bott-manager`.
4. After a Slack conversation, the same `agentos.db` shows a session row with id prefixed `slack:`.

---

### Task 1.1 — Add the shared SQLite db helper

**Files:**
- Modify: `src/bott/shared/config.py`

**Steps:**
- [ ] Add an accessor for the AgentOS db path next to `db_path()`:

```python
def agentos_db_path() -> str:
    """Path to the shared Agno SqliteDb that backs AgentOS sessions/metrics and (now)
    Slack sessions. Separate from the worker's task/trace DB (review_poc.db)."""
    return os.getenv("AGENTOS_DB_PATH", "agentos.db")
```

- [ ] Commit: `feat(config): add agentos_db_path accessor`

---

### Task 1.2 — Make the code-review tools context-free (contextvar-driven)

**Why:** Today `make_review_tools(ctx)` closes over a per-message `SlackContext`, which forces the team to be rebuilt for every Slack message and can't be shared with AgentOS. Replace the closure with a request-scoped `ContextVar` so a single shared agent serves both Slack and HTTP. (The `enqueued` flag is dropped — the Slack layer already adds the 👀 reaction unconditionally in `_converse`, so nothing reads it.)

**Files:**
- Modify: `src/bott/agents/code_review/member.py`
- Test: `tests/test_code_review_member.py` (new)

**Steps:**
- [ ] Replace the `SlackContext` dataclass + `make_review_tools(ctx)` + `build_code_review_agent(ctx, model)` with a contextvar and module-level tools. New `member.py` body (keep the module docstring and the `CODE_REVIEW_ROLE` / `CODE_REVIEW_INSTRUCTIONS` constants and the `extract_pr_ref` import unchanged):

```python
from __future__ import annotations

import contextvars
from typing import Callable, Optional, TypedDict

from agno.agent import Agent

from bott.shared.persistence import store

from .pr_ref import extract_pr_ref

# (CODE_REVIEW_ROLE and CODE_REVIEW_INSTRUCTIONS stay exactly as they are above.)


class ReviewTarget(TypedDict, total=False):
    """Where a queued review should report back. Present for Slack runs, absent for
    UI/HTTP runs (which queue without a Slack post-target)."""

    channel: Optional[str]
    thread_ts: Optional[str]
    trigger_ts: Optional[str]


# Request-scoped Slack target. The Slack handler sets this around team.run(...);
# HTTP/UI runs leave it None.
_review_target: contextvars.ContextVar[Optional[ReviewTarget]] = contextvars.ContextVar(
    "review_target", default=None
)


def set_review_target(target: Optional[ReviewTarget]) -> contextvars.Token:
    return _review_target.set(target)


def reset_review_target(token: contextvars.Token) -> None:
    _review_target.reset(token)


def start_review(pr_url: str) -> str:
    """Queue a code review of a GitHub pull request.

    Args:
        pr_url: The GitHub PR URL or 'owner/repo#number' reference.
    """
    ref = extract_pr_ref(pr_url)
    if not ref:
        return "I couldn't find a PR reference in that — ask the user for the GitHub PR link."
    owner, repo, number = ref
    target = _review_target.get() or {}
    store.enqueue(
        "review",
        {
            "owner": owner, "name": repo, "number": number,
            "channel": target.get("channel"), "thread_ts": target.get("thread_ts"),
            "trigger_ts": target.get("trigger_ts"),
        },
    )
    return f"Queued a review of {owner}/{repo}#{number}."


def start_rereview(reply_text: str = "") -> str:
    """Queue a re-review (another pass) of the PR already reviewed in this thread.

    Args:
        reply_text: The user's follow-up message, so the next pass has their feedback.
    """
    target = _review_target.get() or {}
    if not target.get("thread_ts"):
        return "Re-reviews only work in a Slack thread that already has a review."
    store.enqueue(
        "rereview",
        {
            "channel": target.get("channel"), "thread_ts": target.get("thread_ts"),
            "trigger_ts": target.get("trigger_ts"), "reply_text": reply_text,
        },
    )
    return "Queued another pass."


def review_tools() -> list[Callable]:
    return [start_review, start_rereview]


def build_code_review_agent(model=None) -> Agent:
    """The Code Review member. `model=None` lets it inherit the manager Team's model."""
    return Agent(
        id="code-review",
        name="Code Review Agent",
        role=CODE_REVIEW_ROLE,
        model=model,
        tools=review_tools(),
        instructions=CODE_REVIEW_INSTRUCTIONS,
        telemetry=False,
    )
```

- [ ] Write `tests/test_code_review_member.py`:

```python
from unittest.mock import patch

from bott.agents.code_review import member


def test_start_review_uses_contextvar_target():
    token = member.set_review_target({"channel": "C1", "thread_ts": "111.0", "trigger_ts": "111.0"})
    try:
        with patch.object(member.store, "enqueue") as enq:
            msg = member.start_review("owner/repo#7")
        assert "owner/repo#7" in msg
        kind, args = enq.call_args[0]
        assert kind == "review"
        assert args["channel"] == "C1" and args["number"] == 7
    finally:
        member.reset_review_target(token)


def test_start_review_without_target_queues_no_channel():
    with patch.object(member.store, "enqueue") as enq:
        member.start_review("https://github.com/o/r/pull/9")
    _, args = enq.call_args[0]
    assert args["channel"] is None and args["number"] == 9


def test_start_rereview_requires_thread():
    assert "only work in a Slack thread" in member.start_rereview("fix it")
```

- [ ] Run: `pytest tests/test_code_review_member.py -v` → all pass.
- [ ] Commit: `refactor(code-review): contextvar-scoped review target, stable agent id`

---

### Task 1.3 — Build the manager once, with a shared db

**Files:**
- Modify: `src/bott/manager/manager.py`
- Modify: `src/bott/manager/__init__.py` (exports)
- Test: `tests/test_manager_build.py` (new)

**Steps:**
- [ ] Rewrite `manager.py` to build a single team bound to a db, and update `run_manager` to accept session/user. Keep `NAME/IDENTITY/VOICE/ROUTING_INSTRUCTIONS`:

```python
from __future__ import annotations

from functools import lru_cache

from agno.db.sqlite import SqliteDb
from agno.team import Team, TeamMode

from bott.agents.code_review.member import build_code_review_agent
from bott.shared.config import agentos_db_path, manager_api_key, manager_base_url, manager_model
from bott.shared.model import build_model

from .personality import IDENTITY, NAME, VOICE

ROUTING_INSTRUCTIONS = [
    "Your team can review GitHub pull requests. When someone wants a PR reviewed, or "
    "follows up on a PR already reviewed in this thread, delegate to the Code Review Agent "
    "and pass the PR link or reference along verbatim.",
    "For anything else — greetings, questions about what you do, small talk, questions "
    "about an earlier review — answer yourself; don't delegate.",
]


def build_manager(db: SqliteDb | None = None, model_id: str | None = None) -> Team:
    """Build the manager Team bound to a shared db. Called once per process and reused."""
    model = build_model(
        model_id or manager_model(),
        base_url=manager_base_url(),
        api_key=manager_api_key(),
    )
    return Team(
        id="bott-manager",
        name=NAME,
        model=model,
        members=[build_code_review_agent()],
        mode=TeamMode.coordinate,
        description=IDENTITY,
        instructions=[VOICE, *ROUTING_INSTRUCTIONS],
        db=db,
        telemetry=False,
        markdown=False,
    )


@lru_cache(maxsize=1)
def get_manager() -> Team:
    """Process-wide singleton manager team, bound to the shared AgentOS SqliteDb."""
    return build_manager(db=SqliteDb(db_file=agentos_db_path()))


def run_manager(
    team: Team, text: str, session_id: str | None = None, user_id: str | None = None
) -> str:
    """Run the manager on a user message and return its conversational reply."""
    out = team.run(text, session_id=session_id, user_id=user_id)
    return (out.content or "").strip()
```

- [ ] Update `src/bott/manager/__init__.py` to export `get_manager` alongside the existing names (`build_manager`, `run_manager`). Read the file first; add `get_manager` to the import + `__all__`.
- [ ] Write `tests/test_manager_build.py`:

```python
from bott.manager.manager import build_manager


def test_build_manager_has_id_and_member():
    team = build_manager()  # db=None is fine for a construction smoke test
    assert team.id == "bott-manager"
    assert any(getattr(m, "id", None) == "code-review" for m in team.members)
```

- [ ] Run: `pytest tests/test_manager_build.py -v` → pass. (If `build_model`/network is required at construction, mark the test to patch `build_model`; otherwise it constructs offline.)
- [ ] Commit: `refactor(manager): singleton team bound to shared SqliteDb`

---

### Task 1.4 — Bind Slack runs to persistent sessions

**Files:**
- Modify: `src/bott/interfaces/slack_app.py`

**Steps:**
- [ ] Update imports: replace `from bott.agents.code_review.member import SlackContext` and `from bott.manager import build_manager, run_manager` with:

```python
from bott.agents.code_review.member import ReviewTarget, reset_review_target, set_review_target
from bott.manager import get_manager, run_manager
```

- [ ] In `_converse(...)`, replace the team construction + run block. Current code:

```python
    ctx = SlackContext(channel=channel, thread_ts=thread_ts, trigger_ts=trigger_ts)
    team = build_manager(ctx)
    ...
    try:
        reply = run_manager(team, msg)
```

Replace with (derive a stable session id from the thread, set the contextvar around the run, reset in `finally`):

```python
    team = get_manager()
    session_id = f"slack:{channel}:{thread_ts}"
    target: ReviewTarget = {"channel": channel, "thread_ts": thread_ts, "trigger_ts": trigger_ts}
    token = set_review_target(target)
    try:
        reply = run_manager(team, msg, session_id=session_id, user_id=f"slack:{channel}")
    except Exception as e:  # noqa: BLE001 — never let a chat turn crash the worker/handler
        log.warning("manager error: %s", e)
        reply = "Sorry — I hit a snag just now. Mind trying again in a moment?"
    finally:
        reset_review_target(token)
```

(Keep the `status_ts` placeholder post above and the `to_mrkdwn` + `_update` below exactly as they are.)

- [ ] Run: `pytest -q` → existing suite still green (no test imports `SlackContext`; if any does, update it to the new API).
- [ ] Manual gate: run `python -m bott.interfaces.slack_app`, mention the bot to queue a review and confirm the verdict still posts; reply in-thread to confirm re-review still queues. Confirm `agentos.db` gains a `slack:...` session row.
- [ ] Commit: `feat(slack): persistent Agno sessions per thread via shared manager`

---

### Task 1.5 — AgentOS wrapper + entrypoint (no auth yet)

**Files:**
- Create: `src/bott/interfaces/agentos.py`
- Modify: `pyproject.toml` (add console script)
- Test: `tests/test_agentos_app.py` (new)

**Steps:**
- [ ] Create `src/bott/interfaces/agentos.py`:

```python
"""AgentOS HTTP front door for Bott — the control-plane API the dashboard consumes.

Serves the same manager team + code-review agent as Slack, backed by the SAME SqliteDb
(agentos.db). Runs as a separate process from the Slack server. Auth (JWTMiddleware) is
added in Phase 2.

Run:  agentos-server   (or: python -m bott.interfaces.agentos)
"""

from __future__ import annotations

import os

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

from bott.manager.manager import build_manager
from bott.shared.config import agentos_db_path

_db = SqliteDb(db_file=agentos_db_path())
_team = build_manager(db=_db)
_code_review = _team.members[0]

agent_os = AgentOS(
    id="bott-os",
    name="Bott OS",
    description="Bott — a conversational engineering teammate.",
    agents=[_code_review],
    teams=[_team],
    db=_db,
    telemetry=False,
)
app = agent_os.get_app()


def main() -> None:
    agent_os.serve(app="bott.interfaces.agentos:app", port=int(os.getenv("AGENTOS_PORT", "7777")))


if __name__ == "__main__":
    main()
```

- [ ] In `pyproject.toml`, under `[project.scripts]`, add:

```toml
agentos-server = "bott.interfaces.agentos:main"
```

- [ ] Reinstall the entrypoint: `pip install -e ".[dev]"`.
- [ ] Write `tests/test_agentos_app.py` (uses FastAPI's TestClient; no network needed for `/health`/`/agents` listing):

```python
from fastapi.testclient import TestClient


def test_agentos_lists_agents_and_team(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "test.db"))
    import importlib

    from bott.interfaces import agentos
    importlib.reload(agentos)  # rebuild with the temp db path

    client = TestClient(agentos.app)
    assert client.get("/health").status_code == 200
    agents = client.get("/agents").json()
    assert any(a.get("id") == "code-review" for a in agents)
    teams = client.get("/teams").json()
    assert any(t.get("id") == "bott-manager" for t in teams)
```

- [ ] Run: `pytest tests/test_agentos_app.py -v` → pass. (If a model API key is required at team construction, set a dummy `OPENAI_API_KEY` in the test env via `monkeypatch`.)
- [ ] Manual gate: `agentos-server`, then `curl -s localhost:7777/agents` and `/teams` and `/health`.
- [ ] Commit: `feat(agentos): serve Bott team + code-review agent over HTTP`

---

## Phase 2 — Auth pipe (Google → BFF → JWTMiddleware)

**Outcome:** A throwaway protected page proves the full gate works end to end before any dashboard UI exists.

**Phase gate:**
1. A non-`axelerant.com` Google account is rejected at sign-in with a clear message.
2. An `axelerant.com` account signs in and reaches a protected test page.
3. `curl localhost:7777/agents` with no token → 401; with a token minted by the BFF → 200.
4. The BFF route `GET /api/os/agents` (while signed in) returns the agent list.

---

### Task 2.1 — Add AgentOS JWT validation

**Files:**
- Modify: `src/bott/shared/config.py`
- Modify: `src/bott/interfaces/agentos.py`
- Test: `tests/test_agentos_auth.py` (new)

**Steps:**
- [ ] Add config accessors to `config.py`:

```python
def agentos_jwt_secret() -> str | None:
    """Shared HS256 secret the Next.js BFF signs with and AgentOS verifies. Required to
    enable API auth; when unset, the API runs open (local dev only)."""
    return os.getenv("AGENT_OS_JWT_SECRET") or None


def allowed_email_domain() -> str:
    return os.getenv("ALLOWED_EMAIL_DOMAIN", "axelerant.com")
```

- [ ] In `agentos.py`, after `app = agent_os.get_app()`, add the middleware (only when the secret is set), plus a tiny domain assertion:

```python
from bott.shared.config import agentos_jwt_secret, allowed_email_domain

_secret = agentos_jwt_secret()
if _secret:
    from agno.os.middleware import JWTMiddleware

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[_secret],
        algorithm="HS256",
        validate=True,
        user_id_claim="sub",
        dependencies_claims=["email", "name", "hd"],
        # /health, /docs, /openapi.json, etc. stay public by JWTMiddleware default.
    )
```

> Belt-and-suspenders domain check: the BFF only mints tokens for verified axelerant.com users, so a valid signature already implies an allowed user. If a per-request assertion is desired, add a thin `BaseHTTPMiddleware` that reads `request.state` claims set by `JWTMiddleware` and 403s when `email`/`hd` don't end with `allowed_email_domain()`. Optional for M1; the signing-secret boundary is the real gate.

- [ ] Write `tests/test_agentos_auth.py`:

```python
import importlib
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch, secret="test-secret-at-least-256-bits-long-aaaaaaaa"):
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("AGENT_OS_JWT_SECRET", secret)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from bott.interfaces import agentos
    importlib.reload(agentos)
    return TestClient(agentos.app), secret


def test_agents_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/agents").status_code == 401


def test_agents_accepts_minted_token(tmp_path, monkeypatch):
    client, secret = _client(tmp_path, monkeypatch)
    token = jwt.encode(
        {"sub": "u@axelerant.com", "email": "u@axelerant.com", "hd": "axelerant.com",
         "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        secret, algorithm="HS256",
    )
    r = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
```

- [ ] Run: `pytest tests/test_agentos_auth.py -v` → pass.
- [ ] Commit: `feat(agentos): HS256 JWT auth via env-gated middleware`

---

### Task 2.2 — Install Auth.js + jose; add env scaffolding

**Files:**
- Modify: `agent-ui/package.json`
- Create: `agent-ui/.env.local` (gitignored) and document in `agent-ui/.env.example` if present, else create it
- Modify: `.gitignore` (ensure `agent-ui/.env*.local` ignored — Next's default already does)

**Steps:**
- [ ] From `agent-ui/`: `pnpm add next-auth@beta jose`
- [ ] Create `agent-ui/.env.local`:

```bash
AUTH_SECRET=             # generate: openssl rand -base64 32
AUTH_GOOGLE_ID=          # Google OAuth client id
AUTH_GOOGLE_SECRET=      # Google OAuth client secret
AUTH_URL=http://localhost:3000
ALLOWED_EMAIL_DOMAIN=axelerant.com
AGENT_OS_URL=http://localhost:7777        # server-side only; never NEXT_PUBLIC
AGENT_OS_JWT_SECRET=test-secret-at-least-256-bits-long-aaaaaaaa   # MUST match backend
```

- [ ] Create/append `agent-ui/.env.example` with the same keys (no secret values).
- [ ] Commit: `chore(ui): add auth deps and env scaffolding`

> **Google setup (manual, document in README):** In Google Cloud Console create an OAuth 2.0 Web client; Authorized redirect URI `http://localhost:3000/api/auth/callback/google` (and the prod URL later). Restrict the OAuth consent screen to Internal (Workspace) so only axelerant.com users can consent.

---

### Task 2.3 — Auth.js config with axelerant-only gate

**Files:**
- Create: `agent-ui/src/auth.ts`
- Create: `agent-ui/src/app/api/auth/[...nextauth]/route.ts`
- Create: `agent-ui/src/middleware.ts`

**Steps:**
- [ ] Create `agent-ui/src/auth.ts`:

```ts
import NextAuth from 'next-auth'
import Google from 'next-auth/providers/google'

const ALLOWED_DOMAIN = process.env.ALLOWED_EMAIL_DOMAIN ?? 'axelerant.com'

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      authorization: { params: { hd: ALLOWED_DOMAIN, prompt: 'select_account' } }
    })
  ],
  pages: { signIn: '/sign-in' },
  callbacks: {
    async signIn({ profile }) {
      const hd = (profile as { hd?: string })?.hd
      const email = profile?.email ?? ''
      const verified = (profile as { email_verified?: boolean })?.email_verified
      return (
        verified === true &&
        hd === ALLOWED_DOMAIN &&
        email.toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`)
      )
    },
    async jwt({ token, profile }) {
      if (profile) {
        token.email = profile.email
        token.name = profile.name
        token.hd = (profile as { hd?: string }).hd
        token.picture = (profile as { picture?: string }).picture
      }
      return token
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.email = (token.email as string) ?? session.user.email
        session.user.name = (token.name as string) ?? session.user.name
        session.user.image = (token.picture as string) ?? session.user.image
      }
      return session
    }
  }
})
```

- [ ] Create `agent-ui/src/app/api/auth/[...nextauth]/route.ts`:

```ts
import { handlers } from '@/auth'
export const { GET, POST } = handlers
```

- [ ] Create `agent-ui/src/middleware.ts` (protect everything except sign-in, auth endpoints, and static assets):

```ts
import { auth } from '@/auth'

export default auth((req) => {
  const { pathname } = req.nextUrl
  const isPublic =
    pathname.startsWith('/sign-in') || pathname.startsWith('/api/auth')
  if (!req.auth && !isPublic) {
    const url = new URL('/sign-in', req.nextUrl.origin)
    return Response.redirect(url)
  }
})

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)']
}
```

- [ ] Commit: `feat(ui): Auth.js Google provider, axelerant.com gate, route middleware`

---

### Task 2.4 — Sign-in page

**Files:**
- Create: `agent-ui/src/app/sign-in/page.tsx`

**Steps:**
- [ ] Create `agent-ui/src/app/sign-in/page.tsx` (server component; uses the server `signIn` action). Includes a rejected-user message via the `?error` query Auth.js adds on failed `signIn` callback (`AccessDenied`):

```tsx
import { signIn } from '@/auth'
import { Button } from '@/components/ui/button'

export default async function SignIn({
  searchParams
}: {
  searchParams: Promise<{ error?: string }>
}) {
  const { error } = await searchParams
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-6 bg-background">
      <div className="flex flex-col items-center gap-2">
        <h1 className="text-xl font-medium text-white">Bott OS</h1>
        <p className="text-sm text-muted">Sign in with your axelerant.com account</p>
      </div>
      {error === 'AccessDenied' && (
        <p className="max-w-sm text-center text-sm text-destructive">
          Access is restricted to axelerant.com accounts. Please sign in with your
          Axelerant Google account.
        </p>
      )}
      <form
        action={async () => {
          'use server'
          await signIn('google', { redirectTo: '/' })
        }}
      >
        <Button type="submit" size="lg" className="bg-primary text-background">
          Sign in with Google
        </Button>
      </form>
    </div>
  )
}
```

- [ ] Manual gate (partial): visit `/` unauthenticated → redirected to `/sign-in`. Sign in with a non-axelerant account → `AccessDenied` message. (Full gate completes after Task 2.5.)
- [ ] Commit: `feat(ui): sign-in page with domain-restricted Google button`

---

### Task 2.5 — BFF proxy that mints the AgentOS token

**Files:**
- Create: `agent-ui/src/lib/osToken.ts`
- Create: `agent-ui/src/app/api/os/[...path]/route.ts`

**Steps:**
- [ ] Create `agent-ui/src/lib/osToken.ts` (mints a 5-minute HS256 JWT with jose):

```ts
import { SignJWT } from 'jose'

const secret = new TextEncoder().encode(process.env.AGENT_OS_JWT_SECRET)

export async function mintOsToken(user: {
  email: string
  name?: string | null
}): Promise<string> {
  const domain = process.env.ALLOWED_EMAIL_DOMAIN ?? 'axelerant.com'
  return new SignJWT({ email: user.email, name: user.name ?? '', hd: domain })
    .setProtectedHeader({ alg: 'HS256' })
    .setSubject(user.email)
    .setIssuedAt()
    .setExpirationTime('5m')
    .sign(secret)
}
```

- [ ] Create `agent-ui/src/app/api/os/[...path]/route.ts` — a catch-all proxy for every method, streaming the upstream body back (preserves chat SSE):

```ts
import { auth } from '@/auth'
import { mintOsToken } from '@/lib/osToken'

const OS_URL = process.env.AGENT_OS_URL ?? 'http://localhost:7777'

async function proxy(req: Request, path: string[]) {
  const session = await auth()
  const email = session?.user?.email
  if (!email) return new Response('Unauthorized', { status: 401 })

  const token = await mintOsToken({ email, name: session.user?.name })
  const url = new URL(req.url)
  const target = `${OS_URL}/${path.join('/')}${url.search}`

  const headers = new Headers(req.headers)
  headers.set('Authorization', `Bearer ${token}`)
  headers.delete('host')
  headers.delete('cookie')

  const init: RequestInit = {
    method: req.method,
    headers,
    // @ts-expect-error - duplex required by undici for streaming request bodies
    duplex: 'half',
    body: ['GET', 'HEAD'].includes(req.method) ? undefined : req.body
  }

  const upstream = await fetch(target, init)
  return new Response(upstream.body, {
    status: upstream.status,
    headers: upstream.headers
  })
}

type Ctx = { params: Promise<{ path: string[] }> }
const handler = async (req: Request, ctx: Ctx) =>
  proxy(req, (await ctx.params).path)

export const GET = handler
export const POST = handler
export const DELETE = handler
export const PATCH = handler
export const PUT = handler
```

- [ ] Phase-2 gate (full): with backend `agentos-server` running (with `AGENT_OS_JWT_SECRET` set, matching `.env.local`):
  - `curl -s -o /dev/null -w "%{http_code}" localhost:7777/agents` → `401`.
  - Sign in at `/sign-in`; then in the browser console `fetch('/api/os/agents').then(r=>r.json()).then(console.log)` → agent list.
- [ ] Commit: `feat(ui): BFF proxy mints short-lived JWT and forwards to AgentOS`

---

## Phase 3 — Dashboard UI (shell + Home + Chat + Sessions)

**Outcome:** The screenshot-style dashboard, behind the gate, against real data.

**Phase gate:**
1. `pnpm validate` passes (lint + prettier + typecheck).
2. Manual: signed in → `/` shows AGENTS (code-review), TEAMS (Bott manager), WORKFLOWS (empty state). Sidebar lists all destinations; non-M1 ones show "Coming soon".
3. Chat at `/chat` streams a reply through the proxy. Sessions at `/sessions` lists rows, including a `slack:`-sourced one, and opening one loads it in chat.

---

### Task 3.1 — Repoint the data layer at the BFF proxy

**Why:** Every API call must go through `/api/os` (relative), with no client-held endpoint or token.

**Files:**
- Modify: `agent-ui/src/api/routes.ts`
- Modify: `agent-ui/src/api/os.ts`
- Modify: `agent-ui/src/hooks/useChatActions.ts`
- Modify: `agent-ui/src/store.ts`

**Steps:**
- [ ] In `routes.ts`, change the base so all builders take no host and resolve to the proxy. Replace the file with:

```ts
const OS = '/api/os'

export const APIRoutes = {
  GetAgents: () => `${OS}/agents`,
  AgentRun: () => `${OS}/agents/{agent_id}/runs`,
  Status: () => `${OS}/health`,
  GetSessions: () => `${OS}/sessions`,
  GetSession: (sessionId: string) => `${OS}/sessions/${sessionId}/runs`,
  DeleteSession: (sessionId: string) => `${OS}/sessions/${sessionId}`,
  GetTeams: () => `${OS}/teams`,
  TeamRun: (teamId: string) => `${OS}/teams/${teamId}/runs`,
  DeleteTeamSession: (teamId: string, sessionId: string) =>
    `${OS}/teams/${teamId}/sessions/${sessionId}`
}
```

- [ ] In `os.ts`, drop the `endpoint`/`base`/`authToken` parameters and the `Authorization` header (the proxy adds it). For each function, call the no-arg route builder and use default `Content-Type` headers only. Example for `getAgentsAPI`:

```ts
export const getAgentsAPI = async (): Promise<AgentDetails[]> => {
  try {
    const response = await fetch(APIRoutes.GetAgents(), { method: 'GET' })
    if (!response.ok) {
      toast.error(`Failed to fetch agents: ${response.statusText}`)
      return []
    }
    return await response.json()
  } catch {
    toast.error('Error fetching agents')
    return []
  }
}
```

Apply the same shape to `getStatusAPI`, `getAllSessionsAPI`, `getSessionAPI`, `deleteSessionAPI`, `getTeamsAPI`, `deleteTeamSessionAPI` — remove `base`/`authToken` args, call the new route builders. Keep the `type`/`component_id`/`db_id` query params on sessions.
- [ ] In `useChatActions.ts`: remove `selectedEndpoint`/`authToken` reads and pass no args to the API calls. The `getStatus`/`getAgents`/`getTeams` callbacks lose their `[selectedEndpoint, authToken]` deps. Everything else stays.
- [ ] In `store.ts`: remove `selectedEndpoint`/`setSelectedEndpoint`/`authToken`/`setAuthToken` and the `persist` `partialize` of `selectedEndpoint`. Add `osConfig`/`setOsConfig` and `user`/`setUser`:

```ts
osConfig: { name?: string; available_models?: string[] } | null
setOsConfig: (c: Store['osConfig']) => void
user: { name?: string | null; email?: string | null; image?: string | null } | null
setUser: (u: Store['user']) => void
```

(Initialize both to `null`; trivial setters. Drop the `persist` wrapper's `selectedEndpoint` partialize — persist nothing or just keep `mode`.)
- [ ] Grep for remaining references and fix: `rg "selectedEndpoint|authToken|AuthToken|constructEndpointUrl" agent-ui/src` — update or delete each (the streaming hook in Task 3.2; `AuthToken.tsx` / endpoint UI removed in Task 3.4).
- [ ] Commit: `refactor(ui): route all API calls through the BFF proxy`

---

### Task 3.2 — Repoint the chat streaming hook at the proxy

**Files:**
- Modify: `agent-ui/src/hooks/useAIStreamHandler.tsx`
- Modify: `agent-ui/src/hooks/useAIResponseStream.tsx` (only if it composes the URL)

**Steps:**
- [ ] Read `useAIStreamHandler.tsx`. It currently builds the run URL from `selectedEndpoint` via `APIRoutes.AgentRun(selectedEndpoint)` / `TeamRun` and `constructEndpointUrl`. Replace those with the no-arg builders (`APIRoutes.AgentRun()` → `/api/os/agents/{agent_id}/runs`, substituting the id) and remove the `Authorization` header (proxy adds it). Remove `constructEndpointUrl` usage.
- [ ] If `useAIResponseStream.tsx` only consumes a fully-formed URL + options, leave it; just ensure callers pass the relative proxy URL.
- [ ] Manual gate (after shell exists): a chat message streams token-by-token (not all-at-once), confirming SSE passes through the proxy.
- [ ] Commit: `refactor(ui): stream agent/team runs through the BFF proxy`

---

### Task 3.3 — App shell: layout, Sidebar, TopBar, user footer

**Files:**
- Create: `agent-ui/src/app/(dashboard)/layout.tsx`
- Create: `agent-ui/src/components/layout/Sidebar.tsx`
- Create: `agent-ui/src/components/layout/TopBar.tsx`
- Create: `agent-ui/src/components/layout/UserFooter.tsx`
- Create: `agent-ui/src/components/layout/ComingSoon.tsx`
- Create: `agent-ui/src/components/layout/navItems.ts`
- Create: `agent-ui/src/components/os/OsBootstrap.tsx`

**Steps:**
- [ ] Create `navItems.ts` — the full destination list, each flagged live or coming-soon:

```ts
import {
  Home, MessageSquare, ListTree, Activity, Boxes, GraduationCap, Brain,
  BookOpen, BarChart3, ClipboardCheck, ShieldCheck, CalendarClock, Settings,
  type LucideIcon
} from 'lucide-react'

export type NavItem = {
  label: string
  href: string
  icon: LucideIcon
  live: boolean
  group?: 'studio'
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Home', href: '/', icon: Home, live: true },
  { label: 'Chat', href: '/chat', icon: MessageSquare, live: true },
  { label: 'Sessions', href: '/sessions', icon: ListTree, live: true },
  { label: 'Traces', href: '/traces', icon: Activity, live: false },
  { label: 'Studio', href: '/studio', icon: Boxes, live: false, group: 'studio' },
  { label: 'Learning', href: '/learning', icon: GraduationCap, live: false },
  { label: 'Memory', href: '/memory', icon: Brain, live: false },
  { label: 'Knowledge', href: '/knowledge', icon: BookOpen, live: false },
  { label: 'Metrics', href: '/metrics', icon: BarChart3, live: false },
  { label: 'Evaluation', href: '/evaluation', icon: ClipboardCheck, live: false },
  { label: 'Approvals', href: '/approvals', icon: ShieldCheck, live: false },
  { label: 'Scheduler', href: '/scheduler', icon: CalendarClock, live: false },
  { label: 'Settings', href: '/settings', icon: Settings, live: false }
]
```

- [ ] Create `Sidebar.tsx` (client) — Agno logo header, the nav list (live items are `next/link`; non-live render disabled with a "soon" tag), and `<UserFooter/>` pinned to the bottom. Use the existing dark/orange Tailwind tokens (`text-primary`, `bg-accent`, `text-muted`). Active route via `usePathname()`.
- [ ] Create `TopBar.tsx` (client) — OS name + a health dot driven by `getStatusAPI()` (poll once on mount), and a Refresh button calling `useChatActions().initialize()`. No endpoint/token editing.
- [ ] Create `UserFooter.tsx` (client) — reads `useStore().user` (set by `OsBootstrap`), shows avatar/name/email and a Sign out button:

```tsx
'use client'
import { signOut } from 'next-auth/react'
import { useStore } from '@/store'

export default function UserFooter() {
  const user = useStore((s) => s.user)
  return (
    <div className="flex items-center justify-between gap-2 px-1">
      <div className="flex min-w-0 items-center gap-2">
        {/* avatar: user?.image */}
        <span className="truncate text-xs text-muted">{user?.email ?? ''}</span>
      </div>
      <button
        onClick={() => signOut({ callbackUrl: '/sign-in' })}
        className="text-xs text-primary"
      >
        Sign out
      </button>
    </div>
  )
}
```

> `signOut` from `next-auth/react` needs a client `SessionProvider`. Add it in the root layout (Task 3.6) or call the sign-out route directly via a form `action` to `/api/auth/signout` to avoid the provider. Plan uses `SessionProvider` (Task 3.6).

- [ ] Create `ComingSoon.tsx` — a centered "This section is coming soon" placeholder used by non-M1 routes.
- [ ] Create `OsBootstrap.tsx` (client) — runs `initialize()` once after hydration (replacing the side effect the old chat `Sidebar` performed) and seeds `useStore().user` from the Auth.js session (fetched via `/api/auth/session` or passed from a server layout). Place it in the dashboard layout so every page is initialized.
- [ ] Create `(dashboard)/layout.tsx` (server) — guards the session (`const session = await auth(); if (!session) redirect('/sign-in')`), then renders the shell:

```tsx
import { auth } from '@/auth'
import { redirect } from 'next/navigation'
import Sidebar from '@/components/layout/Sidebar'
import TopBar from '@/components/layout/TopBar'
import OsBootstrap from '@/components/os/OsBootstrap'

export default async function DashboardLayout({
  children
}: {
  children: React.ReactNode
}) {
  const session = await auth()
  if (!session?.user) redirect('/sign-in')
  return (
    <div className="flex h-screen bg-background/80">
      <OsBootstrap
        user={{
          name: session.user.name,
          email: session.user.email,
          image: session.user.image
        }}
      />
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  )
}
```

- [ ] Commit: `feat(ui): dashboard app shell (sidebar, topbar, user footer, bootstrap)`

---

### Task 3.4 — Move Chat under /chat; retire the old chat sidebar

**Files:**
- Create: `agent-ui/src/app/(dashboard)/chat/page.tsx`
- Delete: `agent-ui/src/app/page.tsx` (replaced by Home in Task 3.5)
- Modify: `agent-ui/src/components/chat/ChatArea/ChatArea.tsx` (only if it imports the old `Sidebar`)
- Delete: `agent-ui/src/components/chat/Sidebar/Sidebar.tsx`, `AuthToken.tsx` (and the `Endpoint` block within Sidebar)

**Steps:**
- [ ] Read `ChatArea.tsx`. If it renders or imports the old `Sidebar`, remove that; the shell now owns navigation. The mode/entity selectors (`ModeSelector`, `EntitySelector`) move into a compact header inside the chat page.
- [ ] Create `(dashboard)/chat/page.tsx`:

```tsx
'use client'
import { Suspense } from 'react'
import { ChatArea } from '@/components/chat/ChatArea'

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="p-4 text-muted">Loading…</div>}>
      <ChatArea />
    </Suspense>
  )
}
```

- [ ] Move `ModeSelector` + `EntitySelector` into the chat page header (or a small `ChatHeader` component) so users can still pick agent/team. Keep `Sessions` history out of the chat page (it's now the `/sessions` route), but keep "New Chat" available in the chat header via `useChatActions().clearChat`.
- [ ] Delete `Sidebar.tsx` and `AuthToken.tsx`; remove their barrel exports in `components/chat/Sidebar/index.ts` (keep `Sessions`, `EntitySelector`, `ModeSelector` exports — still used).
- [ ] Run `pnpm typecheck` and fix any dangling imports.
- [ ] Commit: `feat(ui): chat moves to /chat; retire endpoint/token sidebar`

---

### Task 3.5 — Home dashboard

**Files:**
- Create: `agent-ui/src/app/(dashboard)/page.tsx`
- Create: `agent-ui/src/components/home/HomeDashboard.tsx`
- Create: `agent-ui/src/components/home/EntityCard.tsx`
- Create: `agent-ui/src/components/home/EntityGroup.tsx`

**Steps:**
- [ ] Create `EntityCard.tsx` — props `{ kind: 'agent'|'team'|'workflow', id, name, description?, model?, tags?: string[] }`. Renders the icon tile, name, description, tag chips, and CHAT + CONFIG actions. CHAT links to `/chat?type=${kind}&id=${id}` (use `agent`/`team` query keys the chat already reads — map `kind` to the existing `agent`/`team` query params). CONFIG opens a read-only drawer (Radix Dialog already in deps) showing model/id; minimal for M1.
- [ ] Create `EntityGroup.tsx` — a collapsible section (`AGENTS`/`TEAMS`/`WORKFLOWS`) with a responsive grid (`grid gap-4 md:grid-cols-2 xl:grid-cols-3`) and an empty-state line when the list is empty.
- [ ] Create `HomeDashboard.tsx` (client) — reads `agents`/`teams` from `useStore` (populated by `OsBootstrap`/`initialize`), renders three `EntityGroup`s. Workflows = `[]` → empty state ("No workflows yet"). Loading: skeleton cards while `isEndpointLoading`. Endpoint-down: inline banner + Retry (`initialize()`), keyed off `isEndpointActive`.
- [ ] Create `(dashboard)/page.tsx`:

```tsx
import HomeDashboard from '@/components/home/HomeDashboard'
export default function HomePage() {
  return <HomeDashboard />
}
```

- [ ] Manual gate: signed in, `/` shows code-review under AGENTS, Bott manager under TEAMS, empty WORKFLOWS. CHAT navigates to a working chat with that entity preselected.
- [ ] Commit: `feat(ui): Home dashboard with grouped entity cards`

---

### Task 3.6 — Sessions page + session source badge + SessionProvider

**Files:**
- Create: `agent-ui/src/app/(dashboard)/sessions/page.tsx`
- Create: `agent-ui/src/components/sessions/SessionsPage.tsx`
- Modify: `agent-ui/src/app/layout.tsx` (wrap in `SessionProvider`)
- Add coming-soon routes for the non-M1 nav items.

**Steps:**
- [ ] In root `layout.tsx`, wrap children in Auth.js `SessionProvider` so client components (`UserFooter`, `signOut`) work. Add:

```tsx
import { SessionProvider } from 'next-auth/react'
// ...
<body className={`${geistSans.variable} ${dmMono.variable} antialiased`}>
  <SessionProvider>
    <NuqsAdapter>{children}</NuqsAdapter>
  </SessionProvider>
  <Toaster />
</body>
```

- [ ] Create `SessionsPage.tsx` (client) — reuse `getAllSessionsAPI` and the existing `SessionItem`/`DeleteSessionModal` components in a full-page list with the agent/team toggle (reuse `ModeSelector` or a local toggle). Clicking a row sets the `session` (and `agent`/`team`) query params and routes to `/chat`. Derive a source badge: `session_id.startsWith('slack:') ? 'slack' : 'web'`.
- [ ] Create `(dashboard)/sessions/page.tsx` rendering `<SessionsPage/>`.
- [ ] Create coming-soon route pages for each non-live nav item, e.g. `(dashboard)/traces/page.tsx`:

```tsx
import ComingSoon from '@/components/layout/ComingSoon'
export default function Page() {
  return <ComingSoon title="Traces" />
}
```

Repeat for `studio`, `learning`, `memory`, `knowledge`, `metrics`, `evaluation`, `approvals`, `scheduler`, `settings`.
- [ ] Phase-3 gate: `pnpm validate` passes; `/sessions` lists rows incl. a `slack:` one; opening loads it in chat; chat streams.
- [ ] Commit: `feat(ui): full Sessions page, source badges, coming-soon routes`

---

### Task 3.7 — Docs + env example

**Files:**
- Modify: `README.md`, `.env.example`, `agent-ui/README.md`

**Steps:**
- [ ] Document the two new run commands (`agentos-server` and `cd agent-ui && pnpm dev`), the Google OAuth setup, and the matching `AGENT_OS_JWT_SECRET` requirement on both sides.
- [ ] Commit: `docs: dashboard + auth run instructions`

---

## Self-Review — spec coverage

- **Unified AgentOS, shared db** → Tasks 1.1, 1.3, 1.5. ✓
- **Slack sessions visible / unchanged behavior** → Tasks 1.2, 1.4 (+ Phase-1 gate). ✓
- **`user_isolation` off** → not set in Task 1.5 (default `False`). ✓
- **Honest Home (empty workflows)** → Task 3.5 empty state. ✓
- **Custom route shell, all 13 nav items** → Tasks 3.3, 3.6 (`navItems.ts` + coming-soon pages). ✓
- **Chat reuse under /chat** → Task 3.4. ✓
- **Sessions reuse** → Task 3.6. ✓
- **Google OAuth, axelerant-only (hd + email)** → Task 2.3. ✓
- **UI gate (middleware + sign-in)** → Tasks 2.3, 2.4. ✓
- **API gate (BFF mints JWT, JWTMiddleware validates)** → Tasks 2.1, 2.5. ✓
- **No client-held endpoint/token; settings removed** → Tasks 3.1, 3.4. ✓
- **Theming/errors/testing** → existing tokens reused (3.x); `pnpm validate` + pytest gates. ✓
- **Three-phase sequencing with gates** → phase headers above. ✓

## Open risks carried from the spec
- **Streaming through the proxy** (Task 3.2 gate) — verify SSE is not buffered.
- **Agno API shape** for `SqliteDb(db_file=...)`, `team.run(session_id=, user_id=)`, and `JWTMiddleware` import path are pinned to agno 2.6.13; if a signature differs, adjust at the first failing test (1.5 / 2.1) rather than guessing further.
- **JWT secret parity** between `.env.local` and the backend env — both gates (2.1, 2.5) catch a mismatch as a 401.
