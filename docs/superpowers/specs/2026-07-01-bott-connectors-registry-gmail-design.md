# Connectors Phase 4 — Registry + Gmail (domain-delegated) Design

**Date:** 2026-07-01
**Status:** Approved (brainstorm) → spec review
**Scope:** First slice of Connectors (Phase 4). Formalize the connector registry as the real wiring path and land one domain-delegated Google connector — **Gmail, read-only** — end to end, including the isolation-gate proof of per-call "only my mail." Drive/Calendar (same pattern) and Sentry (different auth pattern) are deliberately deferred to follow-on slices.

Related: architecture doc §6 (connector taxonomy — 3 auth patterns). This slice implements the **domain-delegated** pattern and formalizes the seam the other two plug into.

---

## 1. Goals & non-goals

**Goals**
1. Make the connector `REGISTRY` *the* wiring path: `build_agent` sources connector tools from the registry, not from the ad-hoc `connector_tools()`.
2. Register the existing connectors (Jira, Confluence, Slack-read, Memra) as thin registry entries that declare their **auth pattern** — no rewrite of their internals.
3. Add a **domain-delegated Gmail connector (read-only)**: search + read-thread, impersonating the verified caller per call.
4. Prove isolation structurally: impersonation is bound to `run_context.user_id`; there is no parameter by which the model can name another mailbox; a missing/blank identity fails closed.
5. Degrade cleanly when Google delegation isn't configured (friendly message, connector reports unconfigured) — no crash, no leaked trace/token.

**Non-goals (this slice)**
- Gmail **send/draft/modify** (world-changing; a later slice behind the approval gate).
- Drive and Calendar connectors (mechanical repeats of this pattern — separate slices).
- Sentry (MCP or custom client; different auth pattern — separate slice).
- Per-user OAuth connectors (the seam stays; no flow built here).
- Rewriting any existing connector's internals.
- A live Google Workspace round-trip in the automated suite (operator-gated; see §7).

---

## 2. Background: what exists today

- `src/bott/skills/connectors/registry.py` — `Connector` (`name`, `scope` "org"|"user", `tools()`), `OrgConnector`/`UserConnector`, `Registry` (`register`, `all_connectors`, `org_connectors`, `user_connectors`, `list_names`), and the process-wide `REGISTRY`. **Unused scaffolding** — nothing registers into it.
- `src/bott/skills/connectors/__init__.py` — `connector_tools()` imports and concatenates `jira_read_tools()`, `confluence_read_tools()`, `slack_read_tools()`.
- `src/bott/agents/bott_agent.py:121` — `tools.extend(connector_tools())`; Memra wired separately at :123–124 (`if memra_configured(): tools.extend(make_memra_tools(MemraClient()))`).
- Existing connector tools **self-gate**: each tool checks its `config.*_configured()` at call time and returns a plain "not configured" string rather than raising (see `jira_read.py:jira_search`). Registering them unconditionally is therefore safe.
- `src/bott/skills/scheduling.py:394` — `scheduling_tools(db)` is the canonical **closure-factory** pattern: `@tool` functions take `run_context: RunContext` and resolve the caller via `require_user_id(getattr(run_context, "user_id", None))`. The Gmail wrappers follow this exactly.
- `src/bott/shared/identity.py` — `require_user_id(user_id) -> str` raises `IsolationError` on blank/missing. Reused verbatim.
- Agno `GmailTools` (`agno.tools.google.gmail`): `__init__(..., service_account_path=None, delegated_user=None, ...)`. When `service_account_path` (or `GOOGLE_SERVICE_ACCOUNT_FILE`) is set, `_auth()` calls `ServiceAccountCredentials.from_service_account_file(path, scopes, subject=delegated_user)` — i.e. domain-wide delegation. `delegated_user` may also come from the `GOOGLE_DELEGATED_USER` env var. Read methods used: `search_emails(query, count) -> str` and `get_thread(thread_id) -> str`. Google client libs (`google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`) are **not yet installed** — this slice adds them.

---

## 3. The registry as the real wiring path

**Evolve `registry.py`:**
- Add `auth: str = ""` to `Connector`, one of `"org_credential" | "domain_delegated" | "user_oauth"`. Keep `scope` (derived: `domain_delegated`/`user_oauth` → `"user"`, else `"org"`).
- Add `Registry.all_tools() -> list[Callable]`: flatten every registered connector's `tools()` in registration order (called live, so per-connector factory gating is re-evaluated each call).
- Keep `Registry.list_names()` scope-based (`{"org": [...], "user": [...]}`) — unchanged, so the registry lists every registered connector (Gmail included) with no churn to existing consumers/tests. The richer `auth` grouping is available directly off each connector's `.auth`.
- Add a generic adapter so existing connectors become one-liners:

```python
class FunctionConnector(Connector):
    """Wraps an existing tools-list factory as a registry entry. Internals untouched."""
    def __init__(self, name: str, auth: str, tools_fn: Callable[[], list[Callable]]):
        self.name = name
        self.auth = auth
        self.scope = "user" if auth in ("domain_delegated", "user_oauth") else "org"
        self._tools_fn = tools_fn
    def tools(self) -> list[Callable]:
        return self._tools_fn()
```

**New `src/bott/skills/connectors/register_all.py`** — idempotent registration:

```python
def register_all() -> None:
    """Register every connector into REGISTRY exactly once (idempotent)."""
    if REGISTRY.all_connectors():
        return
    REGISTRY.register(FunctionConnector("jira", "org_credential", jira_read_tools))
    REGISTRY.register(FunctionConnector("confluence", "org_credential", confluence_read_tools))
    REGISTRY.register(FunctionConnector("slack", "org_credential", slack_read_tools))
    REGISTRY.register(FunctionConnector("memra", "org_credential",
                      lambda: make_memra_tools(MemraClient()) if memra_configured() else []))
    REGISTRY.register(FunctionConnector("gmail", "domain_delegated", gmail_read_tools))
```

- Memra keeps its conditional gating *inside* the lazy `tools_fn` (never instantiates `MemraClient` unless configured), so the registry stays the single wiring path without changing Memra's runtime behavior.
- `gmail_read_tools()` always returns its wrappers (self-gating at call time), matching the Jira/Confluence/Slack convention.

**`connectors/__init__.py`** — `connector_tools()` becomes a back-compat shim that calls `register_all()` then returns `REGISTRY.all_tools()`. (Keeps any other caller working; `build_agent` will call the registry path directly.)

**`bott_agent.py`** — replace line 121 and the separate Memra block (123–124):

```python
from bott.skills.connectors.register_all import register_all
from bott.skills.connectors.registry import REGISTRY
...
register_all()
tools.extend(REGISTRY.all_tools())  # all connectors (Jira/Confluence/Slack/Memra/Gmail) via the registry
```

Memra's `if memra_configured()` block is removed from `build_agent` (now handled by its registry entry). No other tool wiring changes.

---

## 4. The Gmail delegated connector (`src/bott/skills/connectors/gmail.py`)

**The crux — per-call impersonation bound to the verified caller.** `delegated_user` is a *constructor* param on `GmailTools`, and the shared chat agent is built once — so a statically-built `GmailTools(delegated_user=X)` (or a `GOOGLE_DELEGATED_USER` env var) would freeze the connector to one person. Instead, the wrapper builds a fresh `GmailTools` per call, impersonating the run's verified identity:

```python
# Module-level guarded import: importing this Agno submodule RAISES if the Google client
# libs are absent, so we swallow it here and gate on GmailTools being non-None. Tests patch
# this module attribute with a stub, so the import guard is transparent to them.
try:
    from agno.tools.google.gmail import GmailTools
except Exception:  # noqa: BLE001 — libs missing → connector self-disables
    GmailTools = None

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
_NO_IDENTITY = "I couldn't tell who you are, so I won't read any mail."

def _impersonated(run_context):
    """Build a GmailTools impersonating the VERIFIED caller. Never trusts a model param
    or GOOGLE_DELEGATED_USER for the mailbox — the caller is run_context.user_id only."""
    email = require_user_id(getattr(run_context, "user_id", None))  # raises IsolationError if blank
    return GmailTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[GMAIL_READONLY],
    )

def gmail_read_tools() -> list[Callable]:
    # Factory-level gating, matching jira/confluence/slack: no tools unless delegation
    # is configured AND the Google client libs imported.
    if GmailTools is None or not config.google_delegation_configured():
        return []

    @tool(name="gmail_search")
    def gmail_search(run_context: RunContext, query: str, limit: int = 10) -> str:
        """Search YOUR Gmail (read-only). `query` is Gmail search syntax
        (e.g. 'from:alice newer_than:7d'). Returns matching messages."""
        try:
            gt = _impersonated(run_context)  # raises IsolationError on blank identity
        except IsolationError:
            return _NO_IDENTITY  # fail closed — never fall back to a default mailbox
        try:
            return gt.search_emails(query, limit)
        except Exception as e:  # noqa: BLE001
            log.error("gmail search failed: %s", redact(str(e)))
            return "Couldn't reach Gmail right now."

    @tool(name="gmail_read_thread")
    def gmail_read_thread(run_context: RunContext, thread_id: str) -> str:
        """Read one of YOUR Gmail threads by id (read-only)."""
        try:
            gt = _impersonated(run_context)  # raises IsolationError on blank identity
        except IsolationError:
            return _NO_IDENTITY  # fail closed — never fall back to a default mailbox
        try:
            return gt.get_thread(thread_id)
        except Exception as e:  # noqa: BLE001
            log.error("gmail read_thread failed: %s", redact(str(e)))
            return "Couldn't reach Gmail right now."

    return [gmail_search, gmail_read_thread]
```

- **Factory-level gating** (matches jira/confluence/slack): `gmail_read_tools()` returns `[]` when `GmailTools` failed to import (Google libs missing) or delegation isn't configured. The registry entry still exists (registered unconditionally in `register_all`), so `list_names()` still lists `gmail`. `_NO_IDENTITY` = `"I couldn't tell who you are, so I won't read any mail."` (matches the `scheduling.py` fail-closed convention).
- **Read-only scope only** (`gmail.readonly`). Only search + read-thread are exposed. No send/draft/modify method is ever called.
- **No mailbox parameter.** The only identity source is `run_context.user_id` (the verified Slack email via `resolve_user_identity`). A blank/missing identity fails closed with `_NO_IDENTITY` — the code never constructs `GmailTools` and never falls back to a default mailbox.
- **Per-call construction** (reads the SA JSON + builds the service each call). Acceptable for read-frequency v1; a creds-info cache is a possible later optimization (YAGNI now).
- **Redaction:** any Google/transport error is logged via `redact()` and returned as a generic message — never a raw trace or token.

---

## 5. Config (`src/bott/shared/config.py`)

Two helpers, following the existing env-only `*_configured()` convention (connector creds read `os.getenv` directly — the settings-override path is model-only):

```python
def google_service_account_path() -> str | None:
    return os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH") or None

def google_delegation_configured() -> bool:
    p = google_service_account_path()
    return bool(p) and os.path.exists(p)
```

No secret is stored here — the SA JSON lives on disk at the operator-provided path; only the path is configuration.

**Dependency:** add `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib` to the project dependencies (required by `GmailTools` service-account auth). Guard the import in `gmail.py` so the module still imports when libs are absent (the wrapper returns `_UNCONFIGURED` / a clear message rather than raising at import).

---

## 6. Operator prerequisite (flagged, like the GitHub App scope)

Domain-wide delegation requires a **Google Workspace admin** to:
1. Create a Google Cloud service account + JSON key; place the key on the host; set `GOOGLE_SERVICE_ACCOUNT_PATH`.
2. In the Workspace Admin console → Security → API controls → Domain-wide delegation, authorize the service account's client ID for the single scope `https://www.googleapis.com/auth/gmail.readonly`.

Until both are done, the connector registers but every call returns `_UNCONFIGURED`. This is documented as a setup gate; the code ships behind it (same posture as the GitHub App installation).

---

## 7. Testing

Google's client is mocked throughout the automated suite (no live Workspace). Tests assert on the **impersonation binding and wiring**, not on real mail.

**Isolation gate (the headline):** (patch `config.google_delegation_configured` → `True` so the factory yields the wrappers; patch `GmailTools` to a stub capturing constructor kwargs)
- `gmail_search`/`gmail_read_thread` invoked with a `run_context` for user A construct `GmailTools` with `delegated_user == "a@axelerant.com"`; with B's `run_context`, `delegated_user == "b@axelerant.com"`. Proves impersonation tracks `run_context.user_id`.
- **No mailbox parameter path:** the tool signatures expose only `query`/`thread_id`/`limit` — assert there is no parameter that sets the mailbox (the model cannot request another user's mail).
- **Fail closed:** a `run_context` with `user_id=None`/blank returns `_NO_IDENTITY` and **never constructs `GmailTools`** (assert the patched constructor was not called) — no fallback mailbox.

**Connector / registry:**
- `all_tools()` returns the flattened tools of all registered connectors in registration order (evaluated live).
- `list_names()` (unchanged, scope-based) lists `gmail` under `"user"` and Jira/Confluence/Slack/Memra under `"org"`. The existing `test_connector_registry.py` (asserts the `{"org","user"}` shape) stays green.
- `FunctionConnector` carries the right `auth` (`gmail` → `domain_delegated`; others → `org_credential`) and derives `scope`.
- `register_all()` is idempotent (calling twice doesn't double-register).
- Existing connectors still surface their same tool callables through the registry (no behavior change). The existing `test_connectors_wiring.py` stays green: with Gmail/Memra unconfigured they contribute `[]`, so `connector_tools()` still returns `[]` when all off and still includes `read_slack_thread` when the Slack token is present.
- Memra's registry entry returns `[]` when `memra_configured()` is false and does not instantiate `MemraClient`.

**Wiring:**
- `build_agent` includes the Gmail wrappers in its toolset (via the registry). Existing tools remain present; count/regression check that nothing was dropped.

**Not-configured path:**
- With `google_delegation_configured()` false, `gmail_read_tools()` returns `[]` (no Gmail tools wired), while the `gmail` connector remains registered and listed by `list_names()`.

**Deferred (operator, like the Codex live eval):** a real Workspace round-trip proving an end-to-end "only my mail" read — needs the admin to create + authorize the SA. Tracked as a follow-up gate, not part of this slice's automated suite.

---

## 8. Files

| File | Change |
|---|---|
| `src/bott/skills/connectors/registry.py` | add `auth`; `all_tools()`; `FunctionConnector`; regroup `list_names()` by auth |
| `src/bott/skills/connectors/register_all.py` | **create** — idempotent `register_all()` |
| `src/bott/skills/connectors/gmail.py` | **create** — delegated read-only Gmail connector |
| `src/bott/skills/connectors/__init__.py` | `connector_tools()` → `register_all()` + `REGISTRY.all_tools()` shim |
| `src/bott/agents/bott_agent.py` | wire connectors via the registry; drop the separate Memra block |
| `src/bott/shared/config.py` | `google_service_account_path()`, `google_delegation_configured()` |
| `pyproject.toml` (deps) | add Google client libs |
| `tests/` | isolation gate, registry, wiring, not-configured (new test module(s)) |

---

## 9. Risks / open points

- **Per-call GmailTools construction cost** — reads SA JSON + builds a service each call. Fine for v1 read volume; revisit with a creds-info cache if it ever matters.
- **`GOOGLE_DELEGATED_USER` env var** — must remain unset in every environment; we always pass `delegated_user` explicitly per call, so our explicit arg wins even if it were set. Documented so no one "helpfully" sets it.
- **Global `REGISTRY` mutation across tests** — `register_all()` populates the process-wide `REGISTRY` once (idempotent guard). Because `FunctionConnector.tools()` calls its factory live, gating still reflects the current env/monkeypatch on every `all_tools()` call, so shared global state doesn't leak stale gating between tests. Tests needing a clean registry construct their own `Registry()` instance.
