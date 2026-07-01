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
