from types import SimpleNamespace

import bott.skills.connectors.drive as drive


class _StubDrive:
    """Captures the constructor kwargs so tests can assert the impersonated user."""
    last_kwargs = None

    def __init__(self, **kwargs):
        _StubDrive.last_kwargs = kwargs

    def search_files(self, query, max_results):
        return f"[{_StubDrive.last_kwargs['delegated_user']}] {max_results} for {query}"

    def read_file(self, file_id):
        return f"[{_StubDrive.last_kwargs['delegated_user']}] file {file_id}"


def _configure(monkeypatch):
    monkeypatch.setattr(drive.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(drive.config, "google_service_account_path", lambda: "/tmp/sa.json")
    monkeypatch.setattr(drive, "GoogleDriveTools", _StubDrive)
    _StubDrive.last_kwargs = None


def test_impersonates_verified_caller(monkeypatch):
    _configure(monkeypatch)
    out_a = drive._drive_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "q")
    assert _StubDrive.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "a@axelerant.com" in out_a
    out_b = drive._drive_search_impl(SimpleNamespace(user_id="b@axelerant.com"), "q")
    assert _StubDrive.last_kwargs["delegated_user"] == "b@axelerant.com"
    assert "b@axelerant.com" in out_b


def test_read_file_impersonates_caller(monkeypatch):
    _configure(monkeypatch)
    out = drive._drive_read_file_impl(SimpleNamespace(user_id="a@axelerant.com"), "file-123")
    assert _StubDrive.last_kwargs["delegated_user"] == "a@axelerant.com"
    assert "file" in out


def test_readonly_scope_only(monkeypatch):
    _configure(monkeypatch)
    drive._drive_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert _StubDrive.last_kwargs["scopes"] == ["https://www.googleapis.com/auth/drive.readonly"]


def test_blank_identity_fails_closed(monkeypatch):
    _configure(monkeypatch)
    out = drive._drive_search_impl(SimpleNamespace(user_id=None), "hi")
    assert out == drive._NO_IDENTITY
    assert _StubDrive.last_kwargs is None  # GoogleDriveTools NEVER constructed


def test_no_resource_owner_parameter(monkeypatch):
    import inspect

    # The private impls expose only the expected params — no way to name a resource owner.
    assert set(inspect.signature(drive._drive_search_impl).parameters) == {
        "run_context", "query", "limit"}
    assert set(inspect.signature(drive._drive_read_file_impl).parameters) == {
        "run_context", "file_id"}

    # Also verify the model-facing @tool wrappers expose no identity parameter.
    _configure(monkeypatch)
    tools = drive.drive_read_tools()
    assert tools, "drive_read_tools() returned nothing — cannot check wrapper params"

    FORBIDDEN = {"user", "email", "user_id", "delegated_user", "owner"}
    for t in tools:
        # Agno may wrap the function under .entrypoint; fall back to the object itself.
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
    monkeypatch.setattr(drive.config, "google_delegation_configured", lambda: False)
    monkeypatch.setattr(drive, "GoogleDriveTools", _StubDrive)  # libs present, but not configured
    assert drive.drive_read_tools() == []


def test_factory_gates_off_when_libs_missing(monkeypatch):
    monkeypatch.setattr(drive.config, "google_delegation_configured", lambda: True)
    monkeypatch.setattr(drive, "GoogleDriveTools", None)  # import guard tripped
    assert drive.drive_read_tools() == []


def test_factory_yields_two_tools_when_configured(monkeypatch):
    _configure(monkeypatch)
    tools = drive.drive_read_tools()
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert names == {"drive_search", "drive_read_file"}


def test_client_unavailable_returns_generic_message(monkeypatch):
    """GoogleDriveTools=None with a valid user_id → RuntimeError → generic message, not IsolationError."""
    monkeypatch.setattr(drive, "GoogleDriveTools", None)
    out = drive._drive_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert out == "Couldn't reach Drive right now."


def test_transport_error_is_redacted(monkeypatch):
    _configure(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("token=sk-secret x")

    monkeypatch.setattr(_StubDrive, "search_files", boom)

    # Spy on redact: record calls but delegate to the real implementation.
    real_redact = drive.redact
    redact_calls = []

    def spy_redact(s):
        redact_calls.append(s)
        return real_redact(s)

    monkeypatch.setattr(drive, "redact", spy_redact)

    out = drive._drive_search_impl(SimpleNamespace(user_id="a@axelerant.com"), "hi")
    assert out == "Couldn't reach Drive right now."
    assert "sk-secret" not in out
    # Prove redact() was actually called with the raw error string.
    assert redact_calls, "redact() was never called"
    assert any("sk-secret" in call for call in redact_calls), (
        f"redact() was not called with the raw error text; calls: {redact_calls}"
    )


def test_real_googledrivetools_constructs_readonly(monkeypatch):
    """Guards against read-only scope misconfiguration: construct the REAL GoogleDriveTools
    (auth is lazy, so no network/file needed) and assert only read tools register."""
    import pytest
    if drive.GoogleDriveTools is None:
        pytest.skip("google libs not installed")
    monkeypatch.setattr(drive.config, "google_service_account_path", lambda: "/tmp/sa.json")
    gt = drive._impersonated(SimpleNamespace(user_id="a@axelerant.com"))  # must NOT raise
    fns = set(gt.functions)
    assert "search_files" in fns and "read_file" in fns
    assert not (fns & {"upload_file", "download_file", "list_files"}), (
        f"non-readonly tools registered: {fns & {'upload_file', 'download_file', 'list_files'}}"
    )
