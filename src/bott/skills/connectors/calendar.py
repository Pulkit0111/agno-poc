"""Domain-delegated, read-only Google Calendar connector. Each call impersonates the VERIFIED
caller (run_context.user_id) via Google Workspace domain-wide delegation — so a user only
ever reads their OWN Calendar. The Calendar identity is never a tool parameter and never
GOOGLE_DELEGATED_USER."""

from __future__ import annotations

from typing import Callable

from agno.run import RunContext
from agno.tools import tool

from bott.shared import config
from bott.shared.identity import IsolationError, require_user_id
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.calendar")

# Module-level guarded import: importing this Agno submodule RAISES if the Google client
# libs are absent, so we swallow it here and gate on GoogleCalendarTools being non-None. Tests
# patch this module attribute with a stub, so the import guard is transparent to them.
try:
    from agno.tools.google.calendar import GoogleCalendarTools
except Exception:  # noqa: BLE001 — libs missing → connector self-disables
    GoogleCalendarTools = None

CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
_NO_IDENTITY = "I couldn't tell who you are, so I won't read your calendar."


def _impersonated(run_context):
    """Build a GoogleCalendarTools impersonating the VERIFIED caller. The caller is
    run_context.user_id ONLY — never a model param or GOOGLE_DELEGATED_USER."""
    email = require_user_id(getattr(run_context, "user_id", None))  # raises IsolationError if blank
    if GoogleCalendarTools is None:
        raise RuntimeError("Calendar client unavailable (Google libs not installed).")
    return GoogleCalendarTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[CALENDAR_READONLY],
        # Read-only is structural: enable ONLY the three read methods Bott calls;
        # every write/mutating method is disabled so the toolkit matches calendar.readonly scope.
        list_events=True,
        get_event=True,
        list_calendars=True,
        fetch_all_events=False,
        find_available_slots=False,
        check_availability=False,
        get_event_attendees=False,
        search_events=False,
        create_event=False,
        update_event=False,
        delete_event=False,
        quick_add_event=False,
        move_event=False,
        respond_to_event=False,
    )


def _calendar_list_events_impl(run_context, limit: int = 10, start_date=None) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY  # fail closed — never construct GoogleCalendarTools, never a default user
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("calendar list_events failed: %s", redact(str(e)))
        return "Couldn't reach Calendar right now."
    try:
        return gt.list_events(limit, start_date)
    except Exception as e:  # noqa: BLE001
        log.error("calendar list_events failed: %s", redact(str(e)))
        return "Couldn't reach Calendar right now."


def _calendar_get_event_impl(run_context, event_id: str) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("calendar get_event failed: %s", redact(str(e)))
        return "Couldn't reach Calendar right now."
    try:
        return gt.get_event(event_id)
    except Exception as e:  # noqa: BLE001
        log.error("calendar get_event failed: %s", redact(str(e)))
        return "Couldn't reach Calendar right now."


def _calendar_list_calendars_impl(run_context) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("calendar list_calendars failed: %s", redact(str(e)))
        return "Couldn't reach Calendar right now."
    try:
        return gt.list_calendars()
    except Exception as e:  # noqa: BLE001
        log.error("calendar list_calendars failed: %s", redact(str(e)))
        return "Couldn't reach Calendar right now."


def calendar_read_tools() -> list[Callable]:
    """Read-only Google Calendar tools, gated at the factory: no tools unless the Google libs
    imported AND domain-wide delegation is configured."""
    if GoogleCalendarTools is None or not config.google_delegation_configured():
        return []

    @tool(name="calendar_list_events")
    def calendar_list_events(run_context: RunContext, limit: int = 10, start_date=None) -> str:
        """List YOUR upcoming calendar events (read-only). `start_date` optional ISO date."""
        return _calendar_list_events_impl(run_context, limit, start_date)

    @tool(name="calendar_get_event")
    def calendar_get_event(run_context: RunContext, event_id: str) -> str:
        """Get one of YOUR calendar events by id (read-only)."""
        return _calendar_get_event_impl(run_context, event_id)

    @tool(name="calendar_list_calendars")
    def calendar_list_calendars(run_context: RunContext) -> str:
        """List YOUR calendars (read-only)."""
        return _calendar_list_calendars_impl(run_context)

    return [calendar_list_events, calendar_get_event, calendar_list_calendars]
