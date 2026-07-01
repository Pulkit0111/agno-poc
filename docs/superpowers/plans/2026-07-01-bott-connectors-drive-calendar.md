# Connectors Phase 4 slice 2 — Drive + Calendar (read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add two more domain-delegated, read-only Google connectors — Drive and Calendar — mirroring the proven `connectors/gmail.py`.

**Architecture:** Each is a self-contained module with a guarded toolkit import, `_impersonated(run_context)` binding `delegated_user` to the verified caller, module-level `_impl` functions, and a factory-gated set of `@tool` wrappers. Both register through `REGISTRY` as `domain_delegated`.

**Tech Stack:** Python 3.12, agno 2.6.13 (`agno.tools.google.drive.GoogleDriveTools`, `agno.tools.google.calendar.GoogleCalendarTools`), pytest.

Spec: `docs/superpowers/specs/2026-07-01-bott-connectors-drive-calendar-design.md`

## Global Constraints

- **Read-only, structural:** enable ONLY the read functions the connector calls; set every other toolkit function flag `False`. Pass the `.readonly` scope explicitly. (Leaving write flags at their defaults makes the toolkit constructor raise `ValueError` — this is the whole point.)
- **Isolation:** resource owner is ALWAYS `require_user_id(run_context.user_id)`; never a tool param, never `GOOGLE_DELEGATED_USER`. Blank identity → `_NO_IDENTITY`, toolkit never constructed.
- **Reference template:** `src/bott/skills/connectors/gmail.py` and `tests/test_connectors_gmail.py` — copy their structure exactly (guarded import, `_impersonated`, `_impl`s, factory gating, `@tool` wrappers, redaction via `redact()`, the `_reset`/autouse test fixture already exists in conftest).
- Reuse `config.google_service_account_path()` / `config.google_delegation_configured()` (already exist). No new deps.
- Process: work in-place on `main`, commit-only. No push. No worktree.

---

### Task 1: Drive connector (`connectors/drive.py`)

**Files:** Create `src/bott/skills/connectors/drive.py`; Create `tests/test_connectors_drive.py`.

**Interfaces produced:** `drive.GoogleDriveTools` (module attr, `None` if libs absent), `drive._impersonated(run_context)`, `drive._drive_search_impl(run_context, query, limit=10)`, `drive._drive_read_file_impl(run_context, file_id)`, `drive.drive_read_tools() -> list[Callable]`.

- [ ] **Step 1: Write `tests/test_connectors_drive.py`** — copy `tests/test_connectors_gmail.py` and adapt: stub class `_StubDrive` capturing `__init__(**kwargs)`, with `search_files(self, query, max_results)` returning `f"[{last_kwargs['delegated_user']}] {max_results} for {query}"` and `read_file(self, file_id)` returning `f"[{last_kwargs['delegated_user']}] file {file_id}"`. `_configure(monkeypatch)` patches `drive.config.google_delegation_configured`→True, `drive.config.google_service_account_path`→"/tmp/sa.json", and `drive.GoogleDriveTools`→`_StubDrive`. Tests (mirror the 10 Gmail tests, renamed):
  - `test_impersonates_verified_caller`: `_drive_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "q")` → `last_kwargs["delegated_user"]=="a@axelerant.com"`; then `"b@axelerant.com"`.
  - `test_read_file_impersonates_caller`: `_drive_read_file_impl(...)` for user A → `delegated_user=="a@axelerant.com"`, `"file …"` in output.
  - `test_readonly_scope_only`: after a call, `last_kwargs["scopes"]==["https://www.googleapis.com/auth/drive.readonly"]`.
  - `test_blank_identity_fails_closed`: `user_id=None` → returns `drive._NO_IDENTITY`, `last_kwargs is None`.
  - `test_no_resource_owner_parameter`: `inspect.signature(drive._drive_search_impl).parameters` keys == `{"run_context","query","limit"}`; `_drive_read_file_impl` == `{"run_context","file_id"}`; AND for each tool in `drive.drive_read_tools()` (after `_configure`), `inspect.signature(getattr(t,"entrypoint",t)).parameters` contains none of `{"user","email","user_id","delegated_user","owner"}`.
  - `test_factory_gates_off_when_unconfigured`: `google_delegation_configured`→False (+ `GoogleDriveTools`=_StubDrive) → `drive_read_tools()==[]`.
  - `test_factory_gates_off_when_libs_missing`: `GoogleDriveTools`=None → `drive_read_tools()==[]`.
  - `test_factory_yields_two_tools_when_configured`: names == `{"drive_search","drive_read_file"}`.
  - `test_client_unavailable_returns_generic_message`: configured but `GoogleDriveTools`=None, valid user → `"Couldn't reach Drive right now."`, no raise.
  - `test_transport_error_is_redacted`: spy `drive.redact`; make `_StubDrive.search_files` raise `RuntimeError("token=sk-secret x")`; assert return == `"Couldn't reach Drive right now."`, secret not in return, and `redact` spy called with the raw text.
  - `test_real_googledrivetools_constructs_readonly`: `if drive.GoogleDriveTools is None: pytest.skip(...)`; patch `google_service_account_path`→"/tmp/sa.json"; `gt = drive._impersonated(SimpleNamespace(user_id="a@axelerant.com"))` must NOT raise; `fns=set(gt.functions)`; assert `"search_files" in fns and "read_file" in fns`; assert `not (fns & {"upload_file","download_file","list_files"})`.

- [ ] **Step 2: Run tests, expect fail** — `.venv/bin/python -m pytest tests/test_connectors_drive.py -v` → `ModuleNotFoundError: …connectors.drive`.

- [ ] **Step 3: Write `src/bott/skills/connectors/drive.py`** — copy `gmail.py` structure; use these specifics:
  - Guarded import: `from agno.tools.google.drive import GoogleDriveTools` (→ `None` on `except Exception`).
  - `DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"`; `_NO_IDENTITY = "I couldn't tell who you are, so I won't read any Drive files."`
  - `_impersonated(run_context)`: `email = require_user_id(getattr(run_context,"user_id",None))`; `if GoogleDriveTools is None: raise RuntimeError("Drive client unavailable (Google libs not installed).")`; `return GoogleDriveTools(service_account_path=config.google_service_account_path(), delegated_user=email, scopes=[DRIVE_READONLY], list_files=False, search_files=True, read_file=True, upload_file=False, download_file=False)`.
  - `_drive_search_impl(run_context, query, limit=10)`: identity-guard (except IsolationError → `_NO_IDENTITY`), then `try: return _impersonated(run_context).search_files(query, limit)` `except Exception as e: log.error("drive search failed: %s", redact(str(e))); return "Couldn't reach Drive right now."`
  - `_drive_read_file_impl(run_context, file_id)`: same shape, `.read_file(file_id)`, same generic message.
  - `drive_read_tools()`: `if GoogleDriveTools is None or not config.google_delegation_configured(): return []`; then two `@tool` wrappers `drive_search(run_context, query, limit=10)` ("Search YOUR Google Drive (read-only). `query` is Drive search syntax.") and `drive_read_file(run_context, file_id)` ("Read the content/metadata of one of YOUR Drive files by id (read-only)."), each delegating to its impl; `return [drive_search, drive_read_file]`.
  - `log = get_logger("bott.connectors.drive")`.

- [ ] **Step 4: Run tests, expect pass** — `.venv/bin/python -m pytest tests/test_connectors_drive.py -v` (11 tests; the real-construction test must RUN, not skip). Then `.venv/bin/ruff check src/bott/skills/connectors/drive.py tests/test_connectors_drive.py`.

- [ ] **Step 5: Commit** — `git add src/bott/skills/connectors/drive.py tests/test_connectors_drive.py && git commit -m "feat(connectors): domain-delegated read-only Drive connector"`

---

### Task 2: Calendar connector (`connectors/calendar.py`)

**Files:** Create `src/bott/skills/connectors/calendar.py`; Create `tests/test_connectors_calendar.py`.

**Interfaces produced:** `calendar.GoogleCalendarTools` (module attr), `calendar._impersonated(run_context)`, `calendar._calendar_list_events_impl(run_context, limit=10, start_date=None)`, `calendar._calendar_get_event_impl(run_context, event_id)`, `calendar._calendar_list_calendars_impl(run_context)`, `calendar.calendar_read_tools() -> list[Callable]`.

- [ ] **Step 1: Write `tests/test_connectors_calendar.py`** — copy the Drive test file and adapt. `_StubCalendar` captures `__init__(**kwargs)` with `list_events(self, limit, start_date=None)` → `f"[{last_kwargs['delegated_user']}] {limit} events"`, `get_event(self, event_id)` → `f"[{last_kwargs['delegated_user']}] event {event_id}"`, `list_calendars(self)` → `f"[{last_kwargs['delegated_user']}] calendars"`. Tests (renamed, same shapes as Drive):
  - `test_impersonates_verified_caller`: via `_calendar_list_events_impl` for A then B.
  - `test_get_event_impersonates_caller`, `test_list_calendars_impersonates_caller`.
  - `test_readonly_scope_only`: `last_kwargs["scopes"]==["https://www.googleapis.com/auth/calendar.readonly"]`.
  - `test_write_flags_disabled`: `last_kwargs["create_event"] is False and last_kwargs["update_event"] is False and last_kwargs["delete_event"] is False` (guards the ValueError trap at the kwargs level, complementing the real-construction test).
  - `test_blank_identity_fails_closed`: `user_id=None` → `calendar._NO_IDENTITY`, `last_kwargs is None`.
  - `test_no_resource_owner_parameter`: impl signatures — `_calendar_list_events_impl`=={"run_context","limit","start_date"}, `_calendar_get_event_impl`=={"run_context","event_id"}, `_calendar_list_calendars_impl`=={"run_context"}; and each wrapper from `calendar_read_tools()` exposes none of `{"user","email","user_id","delegated_user","owner"}`.
  - `test_factory_gates_off_when_unconfigured`, `test_factory_gates_off_when_libs_missing`.
  - `test_factory_yields_three_tools_when_configured`: names == `{"calendar_list_events","calendar_get_event","calendar_list_calendars"}`.
  - `test_client_unavailable_returns_generic_message`: → `"Couldn't reach Calendar right now."`
  - `test_transport_error_is_redacted`: spy `calendar.redact`; `list_events` raises `RuntimeError("token=sk-secret x")`; assert generic message + spy called.
  - `test_real_googlecalendartools_constructs_readonly`: skip if `calendar.GoogleCalendarTools is None`; `gt=calendar._impersonated(SimpleNamespace(user_id="a@axelerant.com"))` must NOT raise; `fns=set(gt.functions)`; assert `{"list_events","get_event","list_calendars"} <= fns`; assert `not (fns & {"create_event","update_event","delete_event","respond_to_event","quick_add_event","move_event"})`.

- [ ] **Step 2: Run tests, expect fail** — `ModuleNotFoundError: …connectors.calendar`.

- [ ] **Step 3: Write `src/bott/skills/connectors/calendar.py`** — copy `drive.py` structure; specifics:
  - Guarded import `from agno.tools.google.calendar import GoogleCalendarTools`.
  - `CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"`; `_NO_IDENTITY = "I couldn't tell who you are, so I won't read your calendar."`
  - `_impersonated`: identity + `if GoogleCalendarTools is None: raise RuntimeError("Calendar client unavailable (Google libs not installed).")`; `return GoogleCalendarTools(service_account_path=config.google_service_account_path(), delegated_user=email, scopes=[CALENDAR_READONLY], list_events=True, get_event=True, list_calendars=True, fetch_all_events=False, find_available_slots=False, check_availability=False, get_event_attendees=False, search_events=False, create_event=False, update_event=False, delete_event=False, quick_add_event=False, move_event=False, respond_to_event=False)`.
  - `_calendar_list_events_impl(run_context, limit=10, start_date=None)` → `.list_events(limit, start_date)`; `_calendar_get_event_impl(run_context, event_id)` → `.get_event(event_id)`; `_calendar_list_calendars_impl(run_context)` → `.list_calendars()`. Each with the identity-guard + generic `"Couldn't reach Calendar right now."` on `except Exception` (log `redact(str(e))`).
  - `calendar_read_tools()`: gate `if GoogleCalendarTools is None or not config.google_delegation_configured(): return []`; three `@tool` wrappers: `calendar_list_events(run_context, limit=10, start_date=None)` ("List YOUR upcoming calendar events (read-only). `start_date` optional ISO date."), `calendar_get_event(run_context, event_id)` ("Get one of YOUR calendar events by id (read-only)."), `calendar_list_calendars(run_context)` ("List YOUR calendars (read-only)."); `return [calendar_list_events, calendar_get_event, calendar_list_calendars]`.
  - `log = get_logger("bott.connectors.calendar")`.

- [ ] **Step 4: Run tests, expect pass** — `.venv/bin/python -m pytest tests/test_connectors_calendar.py -v` (12 tests; real-construction test must RUN). Then ruff on both new files.

- [ ] **Step 5: Commit** — `git commit -m "feat(connectors): domain-delegated read-only Calendar connector"`

---

### Task 3: Register Drive + Calendar and verify wiring

**Files:** Modify `src/bott/skills/connectors/register_all.py`; Modify `tests/test_connectors_wiring.py`.

**Interfaces consumed:** `drive.drive_read_tools`, `calendar.calendar_read_tools` (Tasks 1-2); `FunctionConnector`, `REGISTRY` (existing).

- [ ] **Step 1: Add failing wiring tests** (append to `tests/test_connectors_wiring.py`)

```python
def test_drive_and_calendar_registered_and_listed():
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY
    register_all()
    user = REGISTRY.list_names()["user"]
    assert "drive" in user and "calendar" in user and "gmail" in user


def test_drive_calendar_wired_when_configured(monkeypatch):
    import bott.skills.connectors.confluence_read as cr
    import bott.skills.connectors.jira_read as jr
    import bott.skills.connectors.drive as drive
    import bott.skills.connectors.calendar as calendar
    monkeypatch.setattr(jr.config, "jira_configured", lambda: False)
    monkeypatch.setattr(cr.config, "confluence_configured", lambda: False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    for mod in (drive, calendar):
        monkeypatch.setattr(mod.config, "google_delegation_configured", lambda: True)
        monkeypatch.setattr(mod.config, "google_service_account_path", lambda: "/tmp/sa.json")

    class _S:
        def __init__(self, **k): pass

    monkeypatch.setattr(drive, "GoogleDriveTools", _S)
    monkeypatch.setattr(calendar, "GoogleCalendarTools", _S)
    from bott.skills import connectors
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in connectors.connector_tools()}
    assert {"drive_search", "drive_read_file", "calendar_list_events",
            "calendar_get_event", "calendar_list_calendars"} <= names
```

- [ ] **Step 2: Run, expect fail** — the two new tests fail (drive/calendar not registered).

- [ ] **Step 3: Register in `register_all.py`** — add imports `from bott.skills.connectors.drive import drive_read_tools` and `from bott.skills.connectors.calendar import calendar_read_tools`, and inside `register_all()` after the gmail registration:
```python
    REGISTRY.register(FunctionConnector("drive", "domain_delegated", drive_read_tools))
    REGISTRY.register(FunctionConnector("calendar", "domain_delegated", calendar_read_tools))
```

- [ ] **Step 4: Run wiring tests + full suite** — `.venv/bin/python -m pytest tests/test_connectors_wiring.py -v` (all pass, incl. the two pre-existing aggregator tests). Then `.venv/bin/python -m pytest -q` — report counts (expect prior 382 + 11 drive + 12 calendar + 2 wiring ≈ 407 passed / 2 skipped). Then `.venv/bin/ruff check src/bott/skills/connectors/`.

- [ ] **Step 5: Commit** — `git commit -m "feat(connectors): register read-only Drive + Calendar via the registry"`

---

## Self-Review

- Spec coverage: Drive connector → Task 1; Calendar connector → Task 2; registration/wiring → Task 3; read-only-structural + real-construction guard → Steps 1/3 of Tasks 1-2; isolation gate → per-connector tests. ✓
- Placeholder scan: exact kwargs, scopes, method calls, tool names, and test names are all given; "copy gmail.py structure" refers to a concrete in-repo file, not a placeholder. ✓
- Type consistency: `_impersonated`, `*_read_tools`, impl signatures, and tool names are consistent across tasks and match the verified agno method signatures (`search_files(query,max_results)`, `read_file(file_id)`, `list_events(limit,start_date)`, `get_event(event_id)`, `list_calendars()`). ✓
