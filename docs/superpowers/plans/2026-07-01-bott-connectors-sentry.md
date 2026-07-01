# Connectors Phase 4 slice 3 — Sentry (org-credential, read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add a read-only Sentry connector (org-credential, direct REST), mirroring the Jira read connector.

**Architecture:** `SentryClient` (httpx Bearer auth + pure normalizers, like `JiraClient`) → plain self-gating read tools in `sentry_read.py` → registered through `REGISTRY` as `org_credential`.

**Tech Stack:** Python 3.12, httpx, pytest.

Spec: `docs/superpowers/specs/2026-07-01-bott-connectors-sentry-design.md`

## Global Constraints

- **Read-only:** only `list_issues`/`get_issue`/`issue_events`; no assign/resolve/comment/write.
- **Org-credential, shared by design:** one org token for everyone; NO per-user isolation machinery (unlike the Google connectors). This is intended shared access.
- **Self-gating:** each tool returns an "isn't configured" string when `config.sentry_configured()` is false; `sentry_read_tools()` returns `[]` when unconfigured (matches `jira_read`).
- **Redaction:** exceptions caught, logged via `redact()`, returned as a readable message — no tracebacks/tokens to the model or user.
- **Reference templates:** `src/bott/shared/integrations/jira.py` (`JiraClient`) and `src/bott/skills/connectors/jira_read.py` — copy their structure.
- Process: in-place on `main`, commit-only, no push, no worktree.

---

### Task 1: Sentry client + config + read tools

**Files:**
- Modify: `src/bott/shared/config.py` (add `sentry_*` group after the Confluence group)
- Create: `src/bott/shared/integrations/sentry.py`
- Create: `src/bott/skills/connectors/sentry_read.py`
- Test: `tests/test_connectors_sentry.py`

**Interfaces produced:**
- `config.sentry_base_url()`, `config.sentry_org_slug()`, `config.sentry_api_token()`, `config.sentry_configured() -> bool`
- `sentry.SentryClient(base_url, org_slug, api_token, timeout=20)` with `.list_issues(query="is:unresolved", limit=20) -> list[dict]`, `.get_issue(issue_id) -> dict`, `.issue_events(issue_id, limit=5) -> list[dict]`, and `_get(path, params=None)`
- `sentry_read.sentry_list_issues(query="is:unresolved", limit=20) -> str`, `sentry_read.sentry_get_issue(issue_id) -> str`, `sentry_read.sentry_issue_events(issue_id, limit=5) -> str`, `sentry_read.sentry_read_tools() -> list[Callable]`

- [ ] **Step 1: Add config group** (`src/bott/shared/config.py`, after `confluence_configured`)

```python
def sentry_base_url() -> str | None:
    """Sentry instance base (default SaaS)."""
    v = os.getenv("SENTRY_BASE_URL", "https://sentry.io")
    return v.rstrip("/") if v else None


def sentry_org_slug() -> str | None:
    return os.getenv("SENTRY_ORG_SLUG") or None


def sentry_api_token() -> str | None:
    return os.getenv("SENTRY_API_TOKEN") or None


def sentry_configured() -> bool:
    return bool(sentry_org_slug() and sentry_api_token())
```

- [ ] **Step 2: Write the failing tests** (`tests/test_connectors_sentry.py`)

```python
import bott.skills.connectors.sentry_read as sentry_read
from bott.shared.integrations.sentry import SentryClient


def _client(monkeypatch, raw):
    c = SentryClient(base_url="https://sentry.io", org_slug="acme", api_token="t")
    monkeypatch.setattr(c, "_get", lambda path, params=None: raw)
    return c


def test_list_issues_normalizes(monkeypatch):
    raw = [{"id": "1", "shortId": "ACME-1", "title": "Boom", "level": "error",
            "status": "unresolved", "count": "42", "permalink": "https://s/1"}]
    c = _client(monkeypatch, raw)
    out = c.list_issues()
    assert out and out[0]["id"] == "1" and out[0]["shortId"] == "ACME-1"
    assert out[0]["title"] == "Boom" and out[0]["count"] == "42"


def test_get_issue_normalizes(monkeypatch):
    raw = {"id": "9", "shortId": "ACME-9", "title": "NPE", "level": "error",
           "status": "unresolved", "count": "3"}
    c = _client(monkeypatch, raw)
    out = c.get_issue("9")
    assert out["id"] == "9" and out["title"] == "NPE"


def test_issue_events_normalizes_and_limits(monkeypatch):
    raw = [{"eventID": f"e{i}", "message": f"m{i}", "dateCreated": "2026-01-01",
            "tags": []} for i in range(10)]
    c = _client(monkeypatch, raw)
    out = c.issue_events("9", limit=3)
    assert len(out) == 3 and out[0]["eventID"] == "e0"


def test_normalizers_tolerate_missing_keys(monkeypatch):
    c = _client(monkeypatch, [{"id": "1"}])
    out = c.list_issues()
    assert out[0]["id"] == "1"  # no KeyError on absent title/level/count


def test_tools_gate_when_unconfigured(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: False)
    assert "isn't configured" in sentry_read.sentry_list_issues().lower()
    assert "isn't configured" in sentry_read.sentry_get_issue("1").lower()
    assert "isn't configured" in sentry_read.sentry_issue_events("1").lower()
    assert sentry_read.sentry_read_tools() == []


def test_tools_present_when_configured(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: True)
    names = {getattr(t, "__name__", "") for t in sentry_read.sentry_read_tools()}
    assert names == {"sentry_list_issues", "sentry_get_issue", "sentry_issue_events"}


def test_list_tool_formats(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: True)

    class _Stub:
        def list_issues(self, query="is:unresolved", limit=20):
            return [{"id": "1", "shortId": "ACME-1", "title": "Boom", "level": "error",
                     "count": "42", "permalink": "https://s/1", "status": "unresolved"}]

    monkeypatch.setattr(sentry_read, "_client", lambda: _Stub())
    out = sentry_read.sentry_list_issues()
    assert "ACME-1" in out and "Boom" in out


def test_tool_error_is_readable_and_redacted(monkeypatch):
    monkeypatch.setattr(sentry_read.config, "sentry_configured", lambda: True)

    class _Boom:
        def list_issues(self, **k):
            raise RuntimeError("token=sk-secret failed")

    monkeypatch.setattr(sentry_read, "_client", lambda: _Boom())
    out = sentry_read.sentry_list_issues()
    assert "sk-secret" not in out
    assert "sentry" in out.lower()  # readable message names the system
```

- [ ] **Step 3: Run tests, expect fail** — `.venv/bin/python -m pytest tests/test_connectors_sentry.py -v` → `ModuleNotFoundError: …integrations.sentry` / `…connectors.sentry_read`.

- [ ] **Step 4: Implement `src/bott/shared/integrations/sentry.py`**

```python
"""Read-only Sentry REST client (org-credential, Bearer auth) — mirrors JiraClient.
Pure normalizers tolerate missing keys; _get is a thin httpx wrapper."""

from __future__ import annotations

from typing import Any

import httpx


def _norm_issue(i: dict) -> dict:
    i = i or {}
    return {
        "id": i.get("id", ""),
        "shortId": i.get("shortId", ""),
        "title": i.get("title") or i.get("culprit") or "",
        "culprit": i.get("culprit", ""),
        "level": i.get("level", ""),
        "status": i.get("status", ""),
        "count": i.get("count", ""),
        "userCount": i.get("userCount", ""),
        "permalink": i.get("permalink", ""),
        "lastSeen": i.get("lastSeen", ""),
        "assignedTo": (i.get("assignedTo") or {}).get("name", "") if isinstance(i.get("assignedTo"), dict) else "",
    }


def _norm_event(e: dict) -> dict:
    e = e or {}
    return {
        "eventID": e.get("eventID") or e.get("id", ""),
        "message": e.get("message") or e.get("title", ""),
        "dateCreated": e.get("dateCreated", ""),
        "release": (e.get("release") or {}).get("version", "") if isinstance(e.get("release"), dict) else (e.get("release") or ""),
        "environment": e.get("environment", ""),
    }


class SentryClient:
    def __init__(self, base_url: str, org_slug: str, api_token: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.org = org_slug
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = httpx.get(self.base_url + path, headers=self._headers,
                      params=params, timeout=self._timeout)
        r.raise_for_status()
        return r.json()

    def list_issues(self, query: str = "is:unresolved", limit: int = 20) -> list[dict]:
        raw = self._get(f"/api/0/organizations/{self.org}/issues/",
                        {"query": query, "limit": limit})
        return [_norm_issue(i) for i in (raw or [])]

    def get_issue(self, issue_id: str) -> dict:
        return _norm_issue(self._get(f"/api/0/organizations/{self.org}/issues/{issue_id}/"))

    def issue_events(self, issue_id: str, limit: int = 5) -> list[dict]:
        raw = self._get(f"/api/0/organizations/{self.org}/issues/{issue_id}/events/",
                        {"per_page": limit})
        return [_norm_event(e) for e in (raw or [])][:limit]
```

- [ ] **Step 5: Implement `src/bott/skills/connectors/sentry_read.py`**

```python
"""Read-only Sentry connector tools (org-credential). Shared org data — one token reads
the org's incidents for everyone; no per-user isolation applies (intended shared access)."""

from __future__ import annotations

from typing import Callable

from bott.shared import config
from bott.shared.integrations.sentry import SentryClient
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.sentry")

_NOT_CONFIGURED = "Sentry isn't configured (set SENTRY_ORG_SLUG, SENTRY_API_TOKEN)."


def _client() -> SentryClient:
    return SentryClient(
        base_url=config.sentry_base_url(),      # type: ignore[arg-type]
        org_slug=config.sentry_org_slug(),      # type: ignore[arg-type]
        api_token=config.sentry_api_token(),    # type: ignore[arg-type]
    )


def _fmt_issue(i: dict) -> str:
    bits = [i.get("shortId") or i.get("id", "?"), i.get("title", "")]
    meta = " · ".join(x for x in (i.get("level", ""), f"{i.get('count','')} events" if i.get("count") else "",
                                  i.get("status", ""), i.get("permalink", "")) if x)
    return f"- {' — '.join(b for b in bits if b)}" + (f"  ({meta})" if meta else "")


def sentry_list_issues(query: str = "is:unresolved", limit: int = 20) -> str:
    """List Sentry issues (read-only). `query` is Sentry search syntax (e.g. 'is:unresolved
    level:error'). Returns matching issues with shortId, title, level, event count, link."""
    if not config.sentry_configured():
        return _NOT_CONFIGURED
    try:
        issues = _client().list_issues(query, limit)
    except Exception as e:  # noqa: BLE001
        log.error("sentry list failed: %s", redact(str(e)))
        return "Couldn't reach Sentry right now."
    if not issues:
        return f"No Sentry issues matched '{query}'."
    return f"Sentry issues for '{query}':\n" + "\n".join(_fmt_issue(i) for i in issues)


def sentry_get_issue(issue_id: str) -> str:
    """Fetch one Sentry issue by id (read-only)."""
    if not config.sentry_configured():
        return _NOT_CONFIGURED
    try:
        i = _client().get_issue(issue_id)
    except Exception as e:  # noqa: BLE001
        log.error("sentry get failed: %s", redact(str(e)))
        return "Couldn't reach Sentry right now."
    return f"Sentry issue {i.get('shortId') or issue_id}:\n{_fmt_issue(i)}"


def sentry_issue_events(issue_id: str, limit: int = 5) -> str:
    """List recent events for a Sentry issue (read-only): release, environment, summary."""
    if not config.sentry_configured():
        return _NOT_CONFIGURED
    try:
        events = _client().issue_events(issue_id, limit)
    except Exception as e:  # noqa: BLE001
        log.error("sentry events failed: %s", redact(str(e)))
        return "Couldn't reach Sentry right now."
    if not events:
        return f"No recent events for Sentry issue {issue_id}."
    lines = [f"- {e.get('dateCreated','')} · {e.get('environment','')} · "
             f"{e.get('release','')} — {e.get('message','')}".rstrip(" ·—") for e in events]
    return f"Recent events for {issue_id}:\n" + "\n".join(lines)


def sentry_read_tools() -> list[Callable]:
    return ([sentry_list_issues, sentry_get_issue, sentry_issue_events]
            if config.sentry_configured() else [])
```

- [ ] **Step 6: Run tests, expect pass** — `.venv/bin/python -m pytest tests/test_connectors_sentry.py -v` (8 tests). Then `.venv/bin/ruff check src/bott/shared/integrations/sentry.py src/bott/skills/connectors/sentry_read.py src/bott/shared/config.py tests/test_connectors_sentry.py`.

- [ ] **Step 7: Commit** — `git add … && git commit -m "feat(connectors): read-only Sentry connector (org-credential REST client)"`

---

### Task 2: Register Sentry + verify wiring

**Files:**
- Modify: `src/bott/skills/connectors/register_all.py`
- Test: `tests/test_connectors_wiring.py`

- [ ] **Step 1: Add failing wiring tests** (append to `tests/test_connectors_wiring.py`)

```python
def test_sentry_registered_and_listed():
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    assert "sentry" in REGISTRY.list_names()["org"]


def test_sentry_wired_when_configured(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.jira_read as jr
    import bott.skills.connectors.sentry_read as sr
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.setattr(sr.config, "sentry_configured", lambda: True)
    from bott.skills import connectors
    names = {getattr(t, "__name__", getattr(t, "name", "")) for t in connectors.connector_tools()}
    assert {"sentry_list_issues", "sentry_get_issue", "sentry_issue_events"} <= names
```

- [ ] **Step 2: Run, expect fail** — the two new tests fail (sentry not registered).

- [ ] **Step 3: Register in `register_all.py`** — add `from bott.skills.connectors.sentry_read import sentry_read_tools` and, inside `register_all()` (after the memra/gmail group, grouped with the org-credential entries):
```python
    REGISTRY.register(FunctionConnector("sentry", "org_credential", sentry_read_tools))
```

- [ ] **Step 4: Run wiring tests + full suite** — `.venv/bin/python -m pytest tests/test_connectors_wiring.py -v` (all pass incl. pre-existing). Then `.venv/bin/python -m pytest -q` — expect prior 408 + 8 sentry + 2 wiring = 418 passed / 2 skipped (report actual). Then `.venv/bin/ruff check src/bott/skills/connectors/`.

- [ ] **Step 5: Commit** — `git commit -m "feat(connectors): register read-only Sentry via the registry"`

---

## Self-Review

- Spec coverage: config §3 → T1 step 1; client §4 → T1 step 4; tools §5 → T1 step 5; tests §6 → T1 step 2 + T2 step 1; registration §5 → T2 step 3. ✓
- No isolation gate — correct (org-credential, shared by design; §2 rationale). ✓
- Placeholders: full code given for client, tools, config, and all tests; templates (`jira.py`/`jira_read.py`) are concrete in-repo files. ✓
- Type consistency: `SentryClient` methods and `sentry_read` function names/signatures match between tasks, the spec, and the tests. ✓
- Endpoint correctness is a documented live-verify item (unit tests mock `_get`) — not a plan gap. ✓
