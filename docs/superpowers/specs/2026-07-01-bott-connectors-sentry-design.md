# Connectors Phase 4 (slice 3) — Sentry (org-credential, read-only) Design

**Date:** 2026-07-01
**Status:** build (part of the "build the whole app, read-only connectors" mandate)
**Scope:** A read-only **Sentry** connector — the last connector in Phase 4. Direct REST client mirroring `JiraClient` (org-credential), registered through `REGISTRY` as `org_credential`. Read operations only: list issues, get an issue, list an issue's recent events. Sentry *triage* (read → propose fix → approval → implement, reusing Build & Fix) is **Phase 6** and out of scope here.

Mirrors the proven Jira read connector (`shared/integrations/jira.py` + `skills/connectors/jira_read.py`). No new patterns.

---

## 1. Goals / non-goals

**Goals**
1. `shared/integrations/sentry.py` — `SentryClient` (Bearer auth, httpx) with pure normalizers + stateless `_get`.
2. `skills/connectors/sentry_read.py` — plain, self-gating read tools: `sentry_list_issues`, `sentry_get_issue`, `sentry_issue_events`; `sentry_read_tools()` factory returning `[]` when unconfigured.
3. `config` group: `sentry_base_url()`, `sentry_org_slug()`, `sentry_api_token()`, `sentry_configured()`.
4. Register through `REGISTRY` as `org_credential` (scope `"org"`).

**Non-goals**
- Any write (assign/resolve/comment/webhook) — read-only.
- Sentry triage flow (Phase 6).
- MCP transport (direct REST is simpler and matches the other org connectors).
- Per-user anything (Sentry is a shared org credential — intended shared access, not a leak; no isolation-gate extension needed, unlike the delegated Google connectors).

---

## 2. Why org-credential + direct REST (not delegated, not MCP)

Sentry is a shared org system: one org API token reads the org's issues for everyone — the same posture as Jira/Confluence. There is **no per-user data** to isolate, so none of the delegated-connector machinery (per-call impersonation, isolation gate) applies. A direct httpx REST client (like `JiraClient`) is the simplest production-ready fit; MCP would add a server dependency for no benefit. This matches the architecture doc, which groups Sentry with Jira/Confluence/Spin/GitHub under org-credential connectors.

---

## 3. Config (`shared/config.py`, after the Confluence group)

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

Operator provides `SENTRY_ORG_SLUG` + `SENTRY_API_TOKEN` (an org/internal-integration auth token with `event:read`/`project:read`). `SENTRY_BASE_URL` optional (self-hosted). Folds into the consolidated setup list.

---

## 4. `SentryClient` (`shared/integrations/sentry.py`) — mirrors `JiraClient`

```python
class SentryClient:
    def __init__(self, base_url, org_slug, api_token, timeout=20):
        self.base_url = base_url.rstrip("/"); self.org = org_slug
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._timeout = timeout

    def _get(self, path, params=None) -> Any:
        # httpx.get(self.base_url + path, headers=self._headers, params=params, timeout=...)
        # raise_for_status; return .json()

    def list_issues(self, query="is:unresolved", limit=20) -> list[dict]:
        raw = self._get(f"/api/0/organizations/{self.org}/issues/",
                        {"query": query, "limit": limit})
        return [_norm_issue(i) for i in (raw or [])]

    def get_issue(self, issue_id) -> dict:
        return _norm_issue(self._get(f"/api/0/organizations/{self.org}/issues/{issue_id}/"))

    def issue_events(self, issue_id, limit=5) -> list[dict]:
        raw = self._get(f"/api/0/organizations/{self.org}/issues/{issue_id}/events/",
                        {"per_page": limit})
        return [_norm_event(e) for e in (raw or [])][:limit]
```

Pure normalizers `_norm_issue` (id, shortId, title, culprit, level, status, count, userCount, permalink, lastSeen, assignedTo) and `_norm_event` (eventID, message/title, dateCreated, release, environment, a compact exception/culprit summary) tolerate missing keys.

> **Endpoint note (operator/live-verify):** the exact org-level issue paths are taken from Sentry's documented REST API; they are exercised only by mocked unit tests here. Confirming them against the live tenant is an operator step at credential setup (same posture as the Gmail/Drive/Calendar live round-trips). If the org-level `…/organizations/{org}/issues/` path isn't available on the tenant, the fallback is the project-scoped `…/projects/{org}/{project}/issues/` (would add an optional `SENTRY_PROJECT_SLUG`). Kept out of v1 to avoid speculative config.

---

## 5. Read tools (`skills/connectors/sentry_read.py`) — mirrors `jira_read.py`

Plain module-level functions, each self-gating on `config.sentry_configured()`, returning agent-friendly strings, catching exceptions → logged + readable message (no tracebacks/tokens; use `redact`).

- `sentry_list_issues(query="is:unresolved", limit=20) -> str` — formatted list (shortId — title · level · events · link).
- `sentry_get_issue(issue_id: str) -> str` — one issue's detail.
- `sentry_issue_events(issue_id: str, limit=5) -> str` — recent events (release/env + summary).
- `sentry_read_tools() -> list[Callable]` — `[sentry_list_issues, sentry_get_issue, sentry_issue_events] if config.sentry_configured() else []`.
- `_client()` builds `SentryClient` from config (fresh per call, like `jira_read._client`).

Registration (`register_all.py`): `REGISTRY.register(FunctionConnector("sentry", "org_credential", sentry_read_tools))` → `list_names()["org"]` gains `sentry`.

---

## 6. Testing (mirrors `test_connectors_jira.py`)

- **Client normalization:** patch `SentryClient._get` to return canned raw payloads; assert `list_issues`/`get_issue`/`issue_events` normalize correctly (ids, titles, counts; missing keys tolerated).
- **Tool gating:** `config.sentry_configured()` → False → each tool returns "isn't configured …" and `sentry_read_tools() == []`.
- **Tool formatting + error handling:** patch `_client` to a stub; assert formatted output; a raising client → readable "Couldn't reach Sentry…" (redacted, no token/trace).
- **Wiring:** `register_all` lists `sentry` under `"org"`; `connector_tools()` includes the three tools when configured; pre-existing aggregator tests stay green (Sentry contributes `[]` when unconfigured).

No isolation gate (org-credential, shared by design — documented rationale in §2).

---

## 7. Files

| File | Change |
|---|---|
| `src/bott/shared/config.py` | add `sentry_*` config group |
| `src/bott/shared/integrations/sentry.py` | **create** — `SentryClient` + normalizers |
| `src/bott/skills/connectors/sentry_read.py` | **create** — read tools + factory |
| `src/bott/skills/connectors/register_all.py` | register `sentry` (org_credential) |
| `tests/test_connectors_sentry.py` | **create** — client + tool + gating tests |
| `tests/test_connectors_wiring.py` | extend: sentry listed + wired when configured |
