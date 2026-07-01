from types import SimpleNamespace

import bott.skills.connectors.calendar as calendar


class _StubCalendar:
    """Captures the constructor kwargs so tests can assert the impersonated user."""
    last_kwargs = None

    def __init__(self, **kwargs):
        _StubCalendar.last_kwargs = kwargs

    def list_events(self, limit, start_date=None):
        return f"[{_StubCalendar.last_kwargs['delegated_user']}] {limit} events"

    def get_event(self, event_id):
        return f"[{_StubCalendar.last_kwargs['delegated_user']}] event {event_id}"

    def list_calendars(self):
        return f"[{_StubCalendar.last_kwargs['delegated_user']}] calendars"


def _configure(monkeypatch):
    monkeypatch.setattr(calendar.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(calendar.config, "google_service_account_path", lambda: "/tmp/sa.json")
    monkeypatch.setattr(calendar, "GoogleCalendarTools", _StubCalendar)
    _StubCalendar.last_kwargs = None


def test_impersonates_verified_caller(monkeypatch):
    _configure(monkeypatch)
    out_a = calendar._calendar_list_events_impl(SimpleNamespace(user_id="a@axelerant.com"))
    assert _StubCalendar.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "a@axelerant.com" in out_a
    out_b = calendar._calendar_list_events_impl(SimpleNamespace(user_id="b@axelerant.com"))
    assert _StubCalendar.last_kwargs["delegated_user"] == "b@axelerant.com"
    assert "b@axelerant.com" in out_b


def test_get_event_impersonates_caller(monkeypatch):
    _configure(monkeypatch)
    out = calendar._calendar_get_event_impl(SimpleNamespace(user_id="a@axelerant.com"), "evt-123")
    assert _StubCalendar.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "event" in out


def test_list_calendars_impersonates_caller(monkeypatch):
    _configure(monkeypatch)
    out = calendar._calendar_list_calendars_impl(SimpleNamespace(user_id="a@axelerant.com"))
    assert _StubCalendar.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "calendars" in out


def test_readonly_scope_only(monkeypatch):
    _configure(monkeypatch)
    calendar._calendar_list_events_impl(SimpleNamespace(user_id="a@axelerant.com"))
    assert _StubCalendar.last_kwargs["scopes"] == [
        "https://www.googleapis.com/auth/calendar.readonly"
    ]


def test_write_flags_disabled(monkeypatch):
    _configure(monkeypatch)
    calendar._calendar_list_events_impl(SimpleNamespace(user_id="a@axelerant.com"))
    assert _StubCalendar.last_kwargs["create_event"] is False
    assert _StubCalendar.last_kwargs["update_event"] is False
    assert _StubCalendar.last_kwargs["delete_event"] is False


def test_blank_identity_fails_closed(monkeypatch):
    _configure(monkeypatch)
    out = calendar._calendar_list_events_impl(SimpleNamespace(user_id=None))
    assert out == calendar._NO_IDENTITY
    assert _StubCalendar.last_kwargs is None  # GoogleCalendarTools NEVER constructed


def test_no_resource_owner_parameter(monkeypatch):
    import inspect

    # The private impls expose only the expected params — no way to name a resource owner.
    assert set(inspect.signature(calendar._calendar_list_events_impl).parameters) == {
        "run_context", "limit", "start_date"}
    assert set(inspect.signature(calendar._calendar_get_event_impl).parameters) == {
        "run_context", "event_id"}
    assert set(inspect.signature(calendar._calendar_list_calendars_impl).parameters) == {
        "run_context"}

    # Also verify the model-facing @tool wrappers expose no identity parameter.
    _configure(monkeypatch)
    tools = calendar.calendar_read_tools()
    assert tools, "calendar_read_tools() returned nothing — cannot check wrapper params"

    FORBIDDEN = {"user", "email", "user_id", "delegated_user", "owner"}
    for t in tools:
        fn = getattr(t, "entrypoint", t)
        try:
            params = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            import warnings
            warnings.warn(
                f"Could not introspect parameters for tool {t!r}; skipping wrapper check.",
                stacklevel=1,
            )
            continue
        leaked = FORBIDDEN & params
        assert not leaked, (
            f"Tool {getattr(t, 'name', t)!r} exposes forbidden param(s): {leaked}"
        )


def test_factory_gates_off_when_unconfigured(monkeypatch):
    monkeypatch.setattr(calendar.config, "google_delegation_configured", lambda: False)
    monkeypatch.setattr(calendar, "GoogleCalendarTools", _StubCalendar)  # libs present, but not configured
    assert calendar.calendar_read_tools() == []


def test_factory_gates_off_when_libs_missing(monkeypatch):
    monkeypatch.setattr(calendar.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(calendar, "GoogleCalendarTools", None)  # import guard tripped
    assert calendar.calendar_read_tools() == []


def test_factory_yields_three_tools_when_configured(monkeypatch):
    _configure(monkeypatch)
    tools = calendar.calendar_read_tools()
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert names == {"calendar_list_events", "calendar_get_event", "calendar_list_calendars"}


def test_client_unavailable_returns_generic_message(monkeypatch):
    """GoogleCalendarTools=None with a valid user_id → RuntimeError → generic message, not IsolationError."""
    monkeypatch.setattr(calendar, "GoogleCalendarTools", None)
    out = calendar._calendar_list_events_impl(SimpleNamespace(user_id="a@axelerant.com"))
    assert out == "Couldn't reach Calendar right now."


def test_transport_error_is_redacted(monkeypatch):
    _configure(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("token=sk-secret x")

    monkeypatch.setattr(_StubCalendar, "list_events", boom)

    real_redact = calendar.redact
    redact_calls = []

    def spy_redact(s):
        redact_calls.append(s)
        return real_redact(s)

    monkeypatch.setattr(calendar, "redact", spy_redact)

    out = calendar._calendar_list_events_impl(SimpleNamespace(user_id="a@axelerant.com"))
    assert out == "Couldn't reach Calendar right now."
    assert "sk-secret" not in out
    assert redact_calls, "redact() was never called"
    assert any("sk-secret" in call for call in redact_calls), (
        f"redact() was not called with the raw error text; calls: {redact_calls}"
    )


def test_real_googlecalendartools_constructs_readonly(monkeypatch):
    """Guards against read-only scope misconfiguration: construct the REAL GoogleCalendarTools
    (auth is lazy, so no network/file needed) and assert only read tools register."""
    import pytest
    if calendar.GoogleCalendarTools is None:
        pytest.skip("google libs not installed")
    monkeypatch.setattr(calendar.config, "google_service_account_path", lambda: "/tmp/sa.json")
    gt = calendar._impersonated(SimpleNamespace(user_id="a@axelerant.com"))  # must NOT raise
    fns = set(gt.functions)
    assert {"list_events", "get_event", "list_calendars"} <= fns
    assert not (fns & {"create_event", "update_event", "delete_event",
                       "respond_to_event", "quick_add_event", "move_event"}), (
        f"write tools registered: {fns & {'create_event','update_event','delete_event','respond_to_event','quick_add_event','move_event'}}"
    )
