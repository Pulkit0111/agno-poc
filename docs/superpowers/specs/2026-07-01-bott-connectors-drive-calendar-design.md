# Connectors Phase 4 (slice 2) — Drive + Calendar (domain-delegated, read-only) Design

**Date:** 2026-07-01
**Status:** Approved-in-mandate ("build the app per the doc, connectors read-only") → build
**Scope:** Two more domain-delegated read-only Google connectors — **Drive** and **Calendar** — built on the exact pattern proven by the Gmail connector (spec `2026-07-01-bott-connectors-registry-gmail-design.md`). Registered through the connector `REGISTRY`. No writes.

This is a near-mechanical repeat of the Gmail slice. The novel/risky part (registry, delegation mechanism, per-call impersonation, isolation gate, the read-only-structural discipline) is already proven; this slice applies it to two more toolkits and carries forward the **final-review Critical lesson**: agno's Google toolkits raise `ValueError` at construction if write functions are left enabled without the write scope, so read-only must be enforced structurally (disable every non-read function) AND guarded by a test that constructs the *real* toolkit.

---

## 1. Goals / non-goals

**Goals**
1. `connectors/drive.py` — read-only Drive: search files + read a file's content, impersonating the verified caller.
2. `connectors/calendar.py` — read-only Calendar: list events, get an event, list calendars, impersonating the verified caller.
3. Register both through `REGISTRY` as `domain_delegated` (scope `"user"`), reusing the existing Google delegation config.
4. Read-only enforced **structurally** (only read functions enabled at construction) + a real-construction guard test for each.
5. Same isolation guarantees as Gmail: resource owner = `require_user_id(run_context.user_id)`, never a param/env; blank identity fails closed.

**Non-goals**
- Any write/create/update/delete/upload (Drive `upload_file`, Calendar `create/update/delete/respond/move`).
- New config or new auth mechanism — reuse `google_service_account_path()` / `google_delegation_configured()`.
- New deps — the Google client libs added in the Gmail slice cover these.
- Live Workspace round-trip in the automated suite (operator-gated, same as Gmail).

---

## 2. Toolkit facts (verified against installed agno 2.6.13)

Both live in the same namespace as Gmail (`agno.tools.google.*`), both accept `service_account_path` + `delegated_user` (→ `creds.with_subject(delegated_user)`), both fall back to `GOOGLE_DELEGATED_USER` env only when `delegated_user` is unset (we always pass it explicitly, so that env can never redirect us).

**`agno.tools.google.drive.GoogleDriveTools`**
- Read flags default `True`: `list_files`, `search_files`, `read_file`. Write flags default `False`: `upload_file`, `download_file`.
- Auto-infers minimal scopes from enabled tools; validates a read scope is present (raises `ValueError("A Google Drive read scope is required…")` otherwise). Read scope: `https://www.googleapis.com/auth/drive.readonly`.
- Read methods used: `search_files(query, max_results=10, page_token=None) -> str`, `read_file(file_id) -> str`.

**`agno.tools.google.calendar.GoogleCalendarTools`**
- **Trap (same as Gmail):** `create_event`, `update_event`, `delete_event` default `True` → constructor raises `ValueError("The scope …/auth/calendar is required for write operations")` unless the write scope is granted. Must disable all write flags. Other write-ish flags (`quick_add_event`, `move_event`, `respond_to_event`) default `False`.
- Read scope: `https://www.googleapis.com/auth/calendar.readonly`.
- Read methods used: `list_events(limit=10, start_date=None) -> str`, `get_event(event_id) -> str`, `list_calendars() -> str`.

---

## 3. Design — mirrors `connectors/gmail.py` exactly

Each module has: a guarded module-level import (`Tool = None` on failure, so tests patch it), `_impersonated(run_context)`, module-level `_impl` functions (testable directly), and a factory that gates at the factory level and wraps the impls in `@tool`.

**`connectors/drive.py`**

```python
try:
    from agno.tools.google.drive import GoogleDriveTools
except Exception:  # noqa: BLE001 — libs missing → connector self-disables
    GoogleDriveTools = None

DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
_NO_IDENTITY = "I couldn't tell who you are, so I won't read any Drive files."

def _impersonated(run_context):
    email = require_user_id(getattr(run_context, "user_id", None))
    if GoogleDriveTools is None:
        raise RuntimeError("Drive client unavailable (Google libs not installed).")
    return GoogleDriveTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[DRIVE_READONLY],
        list_files=False, search_files=True, read_file=True,   # only the two read ops we call
        upload_file=False, download_file=False,
    )

def _drive_search_impl(run_context, query: str, limit: int = 10) -> str: ...   # search_files(query, limit)
def _drive_read_file_impl(run_context, file_id: str) -> str: ...               # read_file(file_id)
def drive_read_tools() -> list[Callable]:
    if GoogleDriveTools is None or not config.google_delegation_configured():
        return []
    # @tool wrappers: drive_search(run_context, query, limit), drive_read_file(run_context, file_id)
```

**`connectors/calendar.py`**

```python
try:
    from agno.tools.google.calendar import GoogleCalendarTools
except Exception:  # noqa: BLE001
    GoogleCalendarTools = None

CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
_NO_IDENTITY = "I couldn't tell who you are, so I won't read your calendar."

def _impersonated(run_context):
    email = require_user_id(getattr(run_context, "user_id", None))
    if GoogleCalendarTools is None:
        raise RuntimeError("Calendar client unavailable (Google libs not installed).")
    return GoogleCalendarTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[CALENDAR_READONLY],
        list_events=True, get_event=True, list_calendars=True,   # the three read ops we call
        fetch_all_events=False, find_available_slots=False, check_availability=False,
        get_event_attendees=False, search_events=False,
        create_event=False, update_event=False, delete_event=False,
        quick_add_event=False, move_event=False, respond_to_event=False,
    )

def _calendar_list_events_impl(run_context, limit: int = 10, start_date: str | None = None) -> str: ...
def _calendar_get_event_impl(run_context, event_id: str) -> str: ...
def _calendar_list_calendars_impl(run_context) -> str: ...
def calendar_read_tools() -> list[Callable]:
    if GoogleCalendarTools is None or not config.google_delegation_configured():
        return []
    # @tool wrappers delegating to the impls
```

Both impls follow the Gmail impl shape: resolve identity (fail closed to `_NO_IDENTITY` on `IsolationError`), then call the read method inside a `try/except Exception` that logs `redact(str(e))` and returns a generic "Couldn't reach Drive/Calendar right now."

**Registration (`register_all.py`):** add two `FunctionConnector` entries, `auth="domain_delegated"`:
```python
REGISTRY.register(FunctionConnector("drive", "domain_delegated", drive_read_tools))
REGISTRY.register(FunctionConnector("calendar", "domain_delegated", calendar_read_tools))
```
→ `list_names()["user"]` becomes `["gmail", "drive", "calendar"]`.

---

## 4. Testing (per connector, mirroring Gmail)

For each of Drive and Calendar (mock the toolkit via a stub that captures constructor kwargs):
- **Impersonation tracks the caller:** two `run_context`s (A, B) → `delegated_user` == A then B. Would fail if code used a fixed email.
- **No resource-owner parameter:** impl + `@tool`-wrapper signatures expose only the query/id/limit args — no `user`/`email`/`delegated_user`/`owner`/`calendar_id`-as-owner param.
- **Fail closed:** blank `user_id` → `_NO_IDENTITY`, stub constructor never called.
- **Factory gating:** returns `[]` when the toolkit import is `None` or delegation unconfigured; registry entry still listed.
- **Client-unavailable:** toolkit `None` + valid user → generic "Couldn't reach …" (not `_NO_IDENTITY`), no raise.
- **Redaction:** transport error routed through `redact()` (spy asserts it was called with the raw text).
- **Real-construction guard (the C1 lesson):** construct the REAL toolkit (auth is lazy — no network/file), assert no `ValueError` and only read tools in `.functions` (no `create_event`/`upload_file`/etc.). This is the test that would have caught the Gmail Critical.

**Wiring:** `register_all` lists `drive` + `calendar` under `"user"`; `REGISTRY.all_tools()` includes their tools when configured; the pre-existing aggregator tests stay green (both contribute `[]` when unconfigured).

---

## 5. Files

| File | Change |
|---|---|
| `src/bott/skills/connectors/drive.py` | **create** — read-only Drive connector |
| `src/bott/skills/connectors/calendar.py` | **create** — read-only Calendar connector |
| `src/bott/skills/connectors/register_all.py` | register `drive` + `calendar` (domain_delegated) |
| `tests/test_connectors_drive.py` | **create** — isolation gate + real-construction guard |
| `tests/test_connectors_calendar.py` | **create** — isolation gate + real-construction guard |
| `tests/test_connectors_wiring.py` | extend: drive/calendar listed + wired when configured |

Operator prerequisite: the Drive/Calendar `readonly` scopes must be added to the same service-account domain-wide-delegation authorization (alongside `gmail.readonly`). Folds into the single consolidated setup list.
