# Connectors Phase 4 — Registry + Gmail (domain-delegated) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the connector `REGISTRY` the real wiring path and add a domain-delegated, read-only Gmail connector whose mailbox impersonation is bound per-call to the verified caller.

**Architecture:** A generic `FunctionConnector` wraps each existing tools-factory (Jira/Confluence/Slack/Memra) as a thin registry entry declaring its auth pattern; a new `DelegatedConnector`-style Gmail module builds `GmailTools(delegated_user=<verified caller>, scopes=[gmail.readonly])` fresh on every call. `build_agent` sources all connector tools from `REGISTRY.all_tools()` instead of the ad-hoc aggregator.

**Tech Stack:** Python 3.12, Agno 2.6.13 (`agno.tools.google.gmail.GmailTools`, `agno.tools.tool`, `agno.run.RunContext`), pytest, Google API client libs.

Spec: `docs/superpowers/specs/2026-07-01-bott-connectors-registry-gmail-design.md`

## Global Constraints

- **Read-only only:** Gmail uses scope `https://www.googleapis.com/auth/gmail.readonly`; only `search_emails` and `get_thread` are called. No send/draft/modify.
- **Isolation is structural:** the impersonated mailbox is `require_user_id(run_context.user_id)` ONLY — never a tool parameter, never `GOOGLE_DELEGATED_USER`. A blank/missing `user_id` fails closed (returns `_NO_IDENTITY`, never constructs `GmailTools`).
- **Factory-level gating:** every connector's `*_tools()` returns `[]` when unconfigured (matches Jira/Confluence/Slack); the registry entry still exists so the connector is listed.
- **No rewrite of existing connectors' internals** — they are wrapped, not changed.
- **Redaction:** transport errors are logged via `redact()` and returned as a generic message — never a raw trace/token.
- **Process:** work in-place on `main`, commit-only. Do NOT push. No worktrees.
- Agno is pinned at `agno==2.6.13`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/bott/skills/connectors/registry.py` (modify) | add `auth` to `Connector`; `Registry.all_tools()`; `FunctionConnector` adapter |
| `src/bott/skills/connectors/gmail.py` (create) | delegated read-only Gmail connector (`gmail_read_tools`, impls, `_impersonated`) |
| `src/bott/shared/config.py` (modify) | `google_service_account_path()`, `google_delegation_configured()` |
| `pyproject.toml` (modify) | add Google client libs |
| `src/bott/skills/connectors/register_all.py` (create) | idempotent `register_all()` registering all 5 connectors |
| `src/bott/skills/connectors/__init__.py` (modify) | `connector_tools()` → `register_all()` + `REGISTRY.all_tools()` shim |
| `src/bott/agents/bott_agent.py` (modify) | wire connectors via the registry; drop the separate Memra block |
| `tests/test_connector_registry.py` (modify) | add `all_tools()` + `FunctionConnector` tests |
| `tests/test_connectors_gmail.py` (create) | isolation gate, fail-closed, not-configured |
| `tests/test_connectors_wiring.py` (modify) | add gmail-listed + wired-when-configured assertions |

---

### Task 1: Registry primitives (`auth`, `all_tools`, `FunctionConnector`)

**Files:**
- Modify: `src/bott/skills/connectors/registry.py`
- Test: `tests/test_connector_registry.py`

**Interfaces:**
- Produces:
  - `Connector.auth: str` (default `""`)
  - `Registry.all_tools() -> list[Callable]` — flattens every registered connector's `tools()` in registration order, evaluated live
  - `FunctionConnector(name: str, auth: str, tools_fn: Callable[[], list[Callable]])` — `auth` one of `"org_credential"|"domain_delegated"|"user_oauth"`; `.scope` derived (`domain_delegated`/`user_oauth` → `"user"`, else `"org"`); `.tools()` returns `tools_fn()`
- Consumes: nothing (leaf task)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_connector_registry.py`)

```python
def test_all_tools_flattens_in_order():
    reg = registry.Registry()

    def a_tools(): return ["a1", "a2"]
    def b_tools(): return ["b1"]

    reg.register(registry.FunctionConnector("a", "org_credential", a_tools))
    reg.register(registry.FunctionConnector("b", "domain_delegated", b_tools))
    assert reg.all_tools() == ["a1", "a2", "b1"]


def test_function_connector_auth_and_scope():
    org = registry.FunctionConnector("jira", "org_credential", lambda: [])
    deleg = registry.FunctionConnector("gmail", "domain_delegated", lambda: [])
    assert org.auth == "org_credential" and org.scope == "org"
    assert deleg.auth == "domain_delegated" and deleg.scope == "user"


def test_all_tools_evaluated_live():
    reg = registry.Registry()
    state = {"on": False}
    reg.register(registry.FunctionConnector(
        "x", "org_credential", lambda: ["t"] if state["on"] else []))
    assert reg.all_tools() == []
    state["on"] = True
    assert reg.all_tools() == ["t"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_connector_registry.py -v`
Expected: FAIL — `AttributeError: module 'bott.skills.connectors.registry' has no attribute 'FunctionConnector'` (and no `all_tools`).

- [ ] **Step 3: Implement the registry changes** (`src/bott/skills/connectors/registry.py`)

Add `auth` to the base class:

```python
class Connector:
    name: str = ""
    scope: str = ""  # "org" | "user"
    auth: str = ""   # "org_credential" | "domain_delegated" | "user_oauth"

    def tools(self) -> list[Callable]:
        raise NotImplementedError
```

Add the generic adapter (after `UserConnector`):

```python
class FunctionConnector(Connector):
    """Wraps an existing tools-list factory as a registry entry. Internals untouched.
    Gating stays inside the factory, so tools() reflects current config on every call."""

    def __init__(self, name: str, auth: str, tools_fn: Callable[[], list[Callable]]):
        self.name = name
        self.auth = auth
        self.scope = "user" if auth in ("domain_delegated", "user_oauth") else "org"
        self._tools_fn = tools_fn

    def tools(self) -> list[Callable]:
        return self._tools_fn()
```

Add `all_tools()` to `Registry` (alongside `all_connectors`):

```python
    def all_tools(self) -> list[Callable]:
        out: list[Callable] = []
        for c in self._items:
            out.extend(c.tools())
        return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_connector_registry.py -v`
Expected: PASS (all tests, including the existing `test_register_and_classify`).

- [ ] **Step 5: Commit**

```bash
git add src/bott/skills/connectors/registry.py tests/test_connector_registry.py
git commit -m "feat(connectors): registry all_tools() + FunctionConnector adapter"
```

---

### Task 2: Gmail delegated connector (config + deps + module + tests)

**Files:**
- Modify: `src/bott/shared/config.py`
- Modify: `pyproject.toml`
- Create: `src/bott/skills/connectors/gmail.py`
- Test: `tests/test_connectors_gmail.py`

**Interfaces:**
- Consumes: `require_user_id`/`IsolationError` (`bott.shared.identity`); `redact`/`get_logger` (`bott.shared.observability.logging_setup`); `tool` (`agno.tools`); `RunContext` (`agno.run`); `GmailTools` (`agno.tools.google.gmail`).
- Produces:
  - `config.google_service_account_path() -> str | None`
  - `config.google_delegation_configured() -> bool`
  - `gmail.gmail_read_tools() -> list[Callable]`
  - `gmail._gmail_search_impl(run_context, query: str, limit: int = 10) -> str`
  - `gmail._gmail_read_thread_impl(run_context, thread_id: str) -> str`
  - `gmail._impersonated(run_context) -> GmailTools`
  - `gmail.GmailTools` (module attribute; `None` if the Google libs are absent — tests patch it)

- [ ] **Step 1: Add config helpers** (`src/bott/shared/config.py`, near the other connector config, e.g. after `confluence_configured`)

```python
def google_service_account_path() -> str | None:
    """Path to the Google service-account JSON key used for domain-wide delegation."""
    return os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH") or None


def google_delegation_configured() -> bool:
    """True when a service-account key file is configured and present on disk."""
    p = google_service_account_path()
    return bool(p) and os.path.exists(p)
```

- [ ] **Step 2: Write the failing tests** (`tests/test_connectors_gmail.py`)

```python
from types import SimpleNamespace

import bott.skills.connectors.gmail as gmail


class _StubGmail:
    """Captures the constructor kwargs so tests can assert the impersonated mailbox."""
    last_kwargs = None

    def __init__(self, **kwargs):
        _StubGmail.last_kwargs = kwargs

    def search_emails(self, query, count):
        return f"[{_StubGmail.last_kwargs['delegated_user']}] {count} results for {query}"

    def get_thread(self, thread_id):
        return f"[{_StubGmail.last_kwargs['delegated_user']}] thread {thread_id}"


def _configure(monkeypatch):
    monkeypatch.setattr(gmail.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail.config, "google_service_account_path", lambda: "/tmp/sa.json")
    monkeypatch.setattr(gmail, "GmailTools", _StubGmail)
    _StubGmail.last_kwargs = None


def test_impersonates_verified_caller(monkeypatch):
    _configure(monkeypatch)
    out_a = gmail._gmail_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hello")
    assert _StubGmail.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "a@axelerant.com" in out_a
    out_b = gmail._gmail_search_impl(SimpleNamespace(user_id="b@axelerant.com"), "hello")
    assert _StubGmail.last_kwargs["delegated_user"] == "b@axelerant.com"
    assert "b@axelerant.com" in out_b


def test_read_thread_impersonates_caller(monkeypatch):
    _configure(monkeypatch)
    out = gmail._gmail_read_thread_impl(SimpleNamespace(user_id="a@axelerant.com"), "t123")
    assert _StubGmail.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "t123" in out


def test_readonly_scope_only(monkeypatch):
    _configure(monkeypatch)
    gmail._gmail_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert _StubGmail.last_kwargs["scopes"] == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_blank_identity_fails_closed(monkeypatch):
    _configure(monkeypatch)
    out = gmail._gmail_search_impl(SimpleNamespace(user_id=None), "hi")
    assert out == gmail._NO_IDENTITY
    assert _StubGmail.last_kwargs is None  # GmailTools NEVER constructed


def test_no_mailbox_parameter():
    # The wrapper tools expose only query/thread_id/limit — no way to name a mailbox.
    import inspect
    assert set(inspect.signature(gmail._gmail_search_impl).parameters) == {
        "run_context", "query", "limit"}
    assert set(inspect.signature(gmail._gmail_read_thread_impl).parameters) == {
        "run_context", "thread_id"}


def test_factory_gates_off_when_unconfigured(monkeypatch):
    monkeypatch.setattr(gmail.config, "google_delegation_configured", lambda: False)
    monkeypatch.setattr(gmail, "GmailTools", _StubGmail)  # libs present, but not configured
    assert gmail.gmail_read_tools() == []


def test_factory_gates_off_when_libs_missing(monkeypatch):
    monkeypatch.setattr(gmail.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail, "GmailTools", None)  # import guard tripped
    assert gmail.gmail_read_tools() == []


def test_factory_yields_two_tools_when_configured(monkeypatch):
    _configure(monkeypatch)
    tools = gmail.gmail_read_tools()
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert names == {"gmail_search", "gmail_read_thread"}


def test_transport_error_is_redacted(monkeypatch):
    _configure(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("token=sk-secret boom")

    monkeypatch.setattr(_StubGmail, "search_emails", boom)
    out = gmail._gmail_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert out == "Couldn't reach Gmail right now."
    assert "sk-secret" not in out
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_connectors_gmail.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bott.skills.connectors.gmail'`.

- [ ] **Step 4: Implement the Gmail connector** (`src/bott/skills/connectors/gmail.py`)

```python
"""Domain-delegated, read-only Gmail connector. Each call impersonates the VERIFIED
caller (run_context.user_id) via Google Workspace domain-wide delegation — so a user only
ever reads their OWN mail. The mailbox is never a tool parameter and never GOOGLE_DELEGATED_USER."""

from __future__ import annotations

from typing import Callable

from agno.run import RunContext
from agno.tools import tool

from bott.shared import config
from bott.shared.identity import IsolationError, require_user_id
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.gmail")

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
    """Build a GmailTools impersonating the VERIFIED caller. The caller is
    run_context.user_id ONLY — never a model param or GOOGLE_DELEGATED_USER."""
    email = require_user_id(getattr(run_context, "user_id", None))  # raises IsolationError if blank
    return GmailTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[GMAIL_READONLY],
    )


def _gmail_search_impl(run_context, query: str, limit: int = 10) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY  # fail closed — never construct GmailTools, never a default mailbox
    try:
        return gt.search_emails(query, limit)
    except Exception as e:  # noqa: BLE001
        log.error("gmail search failed: %s", redact(str(e)))
        return "Couldn't reach Gmail right now."


def _gmail_read_thread_impl(run_context, thread_id: str) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY
    try:
        return gt.get_thread(thread_id)
    except Exception as e:  # noqa: BLE001
        log.error("gmail read_thread failed: %s", redact(str(e)))
        return "Couldn't reach Gmail right now."


def gmail_read_tools() -> list[Callable]:
    """Read-only Gmail tools, gated at the factory (matches jira/confluence/slack): no tools
    unless the Google libs imported AND domain-wide delegation is configured."""
    if GmailTools is None or not config.google_delegation_configured():
        return []

    @tool(name="gmail_search")
    def gmail_search(run_context: RunContext, query: str, limit: int = 10) -> str:
        """Search YOUR Gmail (read-only). `query` uses Gmail search syntax
        (e.g. 'from:alice newer_than:7d'). Returns matching messages."""
        return _gmail_search_impl(run_context, query, limit)

    @tool(name="gmail_read_thread")
    def gmail_read_thread(run_context: RunContext, thread_id: str) -> str:
        """Read one of YOUR Gmail threads by id (read-only)."""
        return _gmail_read_thread_impl(run_context, thread_id)

    return [gmail_search, gmail_read_thread]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_connectors_gmail.py -v`
Expected: PASS (all 9 tests).

- [ ] **Step 6: Add the Google client libs to `pyproject.toml`**

In the `dependencies = [` list (currently starting with `"agno==2.6.13",`), add:

```toml
    "google-api-python-client>=2.0",
    "google-auth-httplib2>=0.2",
    "google-auth-oauthlib>=1.0",
```

Then install into the venv so the connector functions at runtime (tests already pass without it via the import guard; if the install has no network, that is acceptable for this task's test gate):

Run: `.venv/bin/pip install "google-api-python-client>=2.0" "google-auth-httplib2>=0.2" "google-auth-oauthlib>=1.0"`
Expected: `Successfully installed ...` (or an offline error — non-blocking for tests).

- [ ] **Step 7: Verify the suite is still green and lint passes**

Run: `.venv/bin/python -m pytest tests/test_connectors_gmail.py -q && .venv/bin/ruff check src/bott/skills/connectors/gmail.py src/bott/shared/config.py`
Expected: tests PASS; ruff reports no errors.

- [ ] **Step 8: Commit**

```bash
git add src/bott/skills/connectors/gmail.py src/bott/shared/config.py pyproject.toml tests/test_connectors_gmail.py
git commit -m "feat(connectors): domain-delegated read-only Gmail connector (per-call impersonation)"
```

---

### Task 3: Wire the registry as the connector path

**Files:**
- Create: `src/bott/skills/connectors/register_all.py`
- Modify: `src/bott/skills/connectors/__init__.py`
- Modify: `src/bott/agents/bott_agent.py`
- Test: `tests/test_connectors_wiring.py`

**Interfaces:**
- Consumes: `FunctionConnector`, `Registry.all_tools`, `REGISTRY` (Task 1); `gmail_read_tools` (Task 2); the existing `jira_read_tools`/`confluence_read_tools`/`slack_read_tools`; `make_memra_tools`/`MemraClient` (`bott.shared.context`); `memra_configured` (`bott.shared.config`).
- Produces: `register_all.register_all() -> None` (idempotent); `connectors.connector_tools()` now sources from the registry.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_connectors_wiring.py`)

```python
def test_gmail_registered_and_listed(monkeypatch):
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    assert "gmail" in REGISTRY.list_names()["user"]
    assert {"jira", "confluence", "slack", "memra"} <= set(REGISTRY.list_names()["org"])


def test_gmail_wired_when_configured(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.gmail as gmail
    import bott.skills.connectors.jira_read as jr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.setattr(gmail.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(gmail.config, "google_service_account_path", lambda: "/tmp/sa.json")

    class _Stub:
        def __init__(self, **k): pass

    monkeypatch.setattr(gmail, "GmailTools", _Stub)
    from bott.skills import connectors
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in connectors.connector_tools()}
    assert "gmail_search" in names and "gmail_read_thread" in names


def test_register_all_idempotent():
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    n = len(REGISTRY.all_connectors())
    register_all()
    assert len(REGISTRY.all_connectors()) == n
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_connectors_wiring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bott.skills.connectors.register_all'`.

- [ ] **Step 3: Create `register_all.py`** (`src/bott/skills/connectors/register_all.py`)

```python
"""Register every connector into the process-wide REGISTRY exactly once. This is THE
connector wiring path — build_agent reads REGISTRY.all_tools(). Existing connectors are
wrapped as thin FunctionConnector entries (internals untouched); Gmail is domain-delegated."""

from __future__ import annotations

from bott.shared.config import memra_configured
from bott.shared.context import MemraClient, make_memra_tools
from bott.skills.connectors.confluence_read import confluence_read_tools
from bott.skills.connectors.gmail import gmail_read_tools
from bott.skills.connectors.jira_read import jira_read_tools
from bott.skills.connectors.registry import REGISTRY, FunctionConnector
from bott.skills.connectors.slack_read import slack_read_tools


def _memra_tools():
    # Gating stays inside the factory: never instantiate MemraClient unless configured.
    return make_memra_tools(MemraClient()) if memra_configured() else []


def register_all() -> None:
    """Idempotent: registers all connectors on first call, no-ops thereafter."""
    if REGISTRY.all_connectors():
        return
    REGISTRY.register(FunctionConnector("jira", "org_credential", jira_read_tools))
    REGISTRY.register(FunctionConnector("confluence", "org_credential", confluence_read_tools))
    REGISTRY.register(FunctionConnector("slack", "org_credential", slack_read_tools))
    REGISTRY.register(FunctionConnector("memra", "org_credential", _memra_tools))
    REGISTRY.register(FunctionConnector("gmail", "domain_delegated", gmail_read_tools))
```

- [ ] **Step 4: Update the `connector_tools()` shim** (`src/bott/skills/connectors/__init__.py`)

Replace the whole file body with:

```python
"""Connector wiring. The REGISTRY is the single source of truth; connector_tools() is kept
as a back-compat shim that registers all connectors then returns their flattened tools."""

from typing import Callable


def connector_tools() -> list[Callable]:
    from .register_all import register_all
    from .registry import REGISTRY

    register_all()
    return REGISTRY.all_tools()
```

- [ ] **Step 5: Run the wiring tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_connectors_wiring.py -v`
Expected: PASS — including the pre-existing `test_aggregator_gates_all_off` and `test_aggregator_includes_slack_when_token_present` (Gmail/Memra contribute `[]` when unconfigured).

- [ ] **Step 6: Wire `build_agent` through the registry** (`src/bott/agents/bott_agent.py`)

Replace the connectors import (`from bott.skills.connectors import connector_tools`) with:

```python
from bott.skills.connectors.register_all import register_all
from bott.skills.connectors.registry import REGISTRY
```

Replace line 121 (`tools.extend(connector_tools())  # ...`) and the Memra block (lines ~122-124, `if memra_configured(): tools.extend(make_memra_tools(MemraClient()))`) with:

```python
    register_all()
    tools.extend(REGISTRY.all_tools())  # all connectors (Jira/Confluence/Slack/Memra/Gmail) via the registry
```

Then remove the now-unused imports from the top of the file: `memra_configured` (from the `bott.shared.config` import group) and `from bott.shared.context import MemraClient, make_memra_tools` — **only if** no other code in the file references them (grep first).

- [ ] **Step 7: Verify no dropped tools, whole suite green, lint clean**

Run: `.venv/bin/python -c "import re,subprocess"` — then confirm nothing else uses the removed imports:
Run: `grep -n "memra_configured\|MemraClient\|make_memra_tools\|connector_tools" src/bott/agents/bott_agent.py`
Expected: no matches (all removed).

Run: `.venv/bin/python -m pytest tests/test_app_construct.py tests/test_connectors_wiring.py tests/test_connector_registry.py tests/test_connectors_gmail.py -q`
Expected: PASS.

Run: `.venv/bin/ruff check src/bott/agents/bott_agent.py src/bott/skills/connectors/`
Expected: no errors (no unused imports).

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (prior baseline 365 passed / 2 skipped, plus the new tests).

- [ ] **Step 9: Commit**

```bash
git add src/bott/skills/connectors/register_all.py src/bott/skills/connectors/__init__.py src/bott/agents/bott_agent.py tests/test_connectors_wiring.py
git commit -m "feat(connectors): registry is the connector wiring path (incl. Gmail + Memra)"
```

---

## Self-Review

**1. Spec coverage:**
- Registry as wiring path (spec §3) → Task 1 (primitives) + Task 3 (register_all, shim, build_agent). ✓
- Existing connectors as thin entries declaring auth (spec §3) → Task 3 `register_all` `FunctionConnector`s. ✓
- Memra gated inside its factory (spec §3) → Task 3 `_memra_tools`. ✓
- Delegated Gmail read-only, per-call impersonation (spec §4) → Task 2 `_impersonated`/impls. ✓
- Config helpers + deps (spec §5) → Task 2 steps 1, 6. ✓
- `list_names()` unchanged scope shape (spec §3) → not modified; existing test preserved. ✓
- Isolation gate: impersonation tracks caller, no mailbox param, fail-closed (spec §7) → Task 2 tests `test_impersonates_verified_caller`, `test_no_mailbox_parameter`, `test_blank_identity_fails_closed`. ✓
- Not-configured path (spec §7) → Task 2 `test_factory_gates_off_*`. ✓
- Redaction (spec §4) → Task 2 `test_transport_error_is_redacted`. ✓
- Operator prerequisite (spec §6) → documented; no code (correct — it's a setup gate). ✓
- Live Workspace round-trip deferred (spec §7) → not in plan (correct). ✓

**2. Placeholder scan:** none — every code/test step is complete.

**3. Type consistency:** `FunctionConnector(name, auth, tools_fn)`, `all_tools()`, `_gmail_search_impl(run_context, query, limit)`, `_gmail_read_thread_impl(run_context, thread_id)`, `gmail_read_tools()`, `google_delegation_configured()`/`google_service_account_path()`, `register_all()` — names/signatures identical across Tasks 1→3 and the spec. Gmail read methods `search_emails(query, count)` / `get_thread(thread_id)` match the installed `agno.tools.google.gmail` API.
