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


def test_no_mailbox_parameter(monkeypatch):
    import inspect

    # The private impls expose only the expected params — no way to name a mailbox.
    assert set(inspect.signature(gmail._gmail_search_impl).parameters) == {
        "run_context", "query", "limit"}
    assert set(inspect.signature(gmail._gmail_read_thread_impl).parameters) == {
        "run_context", "thread_id"}

    # Also verify the model-facing @tool wrappers expose no mailbox/identity parameter.
    _configure(monkeypatch)
    tools = gmail.gmail_read_tools()
    assert tools, "gmail_read_tools() returned nothing — cannot check wrapper params"

    FORBIDDEN = {"mailbox", "email", "user", "user_id", "delegated_user"}
    for t in tools:
        # Agno may wrap the function under .entrypoint; fall back to the object itself.
        fn = getattr(t, "entrypoint", t)
        try:
            params = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            # If introspection is genuinely infeasible on this Agno version, skip with a note.
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

    # Spy on redact: record calls but delegate to the real implementation.
    real_redact = gmail.redact
    redact_calls = []

    def spy_redact(s):
        redact_calls.append(s)
        return real_redact(s)

    monkeypatch.setattr(gmail, "redact", spy_redact)

    out = gmail._gmail_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert out == "Couldn't reach Gmail right now."
    assert "sk-secret" not in out
    # Prove redact() was actually called with the raw error string.
    assert redact_calls, "redact() was never called"
    assert any("sk-secret" in call for call in redact_calls), (
        f"redact() was not called with the raw error text; calls: {redact_calls}"
    )


def test_client_unavailable_returns_generic_message(monkeypatch):
    """GmailTools=None with a valid user_id → RuntimeError → generic message, not IsolationError."""
    monkeypatch.setattr(gmail, "GmailTools", None)
    out = gmail._gmail_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert out == "Couldn't reach Gmail right now."


def test_real_gmailtools_constructs_readonly(monkeypatch):
    """Guards against the compose/modify-scope ValueError: construct the REAL GmailTools
    (auth is lazy, so no network/file needed) and assert only read-only tools register."""
    import pytest
    if gmail.GmailTools is None:
        pytest.skip("google libs not installed")
    monkeypatch.setattr(gmail.config, "google_service_account_path", lambda: "/tmp/sa.json")
    gt = gmail._impersonated(SimpleNamespace(user_id="a@axelerant.com"))  # must NOT raise
    fns = set(gt.functions)
    assert "search_emails" in fns and "get_thread" in fns
    forbidden = {"send_email", "create_draft_email", "send_email_reply", "update_draft",
                 "send_draft", "apply_label", "remove_label", "trash_message",
                 "star_email", "mark_email_as_read", "get_message", "search_threads"}
    assert not (fns & forbidden), f"non-readonly tools registered: {fns & forbidden}"
