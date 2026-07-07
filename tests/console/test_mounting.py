"""The mounting rule, tested without booting the whole AgentOS app: the helper
decides from env whether the console router should mount, and a half-configured
console (intent vars present, secret missing) fails loud instead of 404ing silently."""
import pytest

from bott.interfaces.console.router import require_console_env, should_mount_console


def test_mounts_when_secret_set(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "x")
    assert should_mount_console() is True


def test_skips_without_secret(monkeypatch):
    monkeypatch.delenv("CONSOLE_SESSION_SECRET", raising=False)
    assert should_mount_console() is False


def _clear_console_env(monkeypatch):
    for var in ("CONSOLE_SESSION_SECRET", "SLACK_CLIENT_ID", "CONSOLE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


def test_intent_without_secret_fails_loud(monkeypatch):
    _clear_console_env(monkeypatch)
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    with pytest.raises(RuntimeError, match="CONSOLE_SESSION_SECRET"):
        require_console_env()


def test_base_url_without_secret_fails_loud(monkeypatch):
    _clear_console_env(monkeypatch)
    monkeypatch.setenv("CONSOLE_BASE_URL", "https://console.example.com")
    with pytest.raises(RuntimeError, match="CONSOLE_BASE_URL"):
        require_console_env()


def test_slack_only_install_stays_valid(monkeypatch):
    # No console vars at all — skip mounting, no crash.
    _clear_console_env(monkeypatch)
    require_console_env()  # must not raise
    assert should_mount_console() is False


def test_fully_configured_console_passes(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "x")
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("CONSOLE_BASE_URL", "https://console.example.com")
    require_console_env()  # must not raise
    assert should_mount_console() is True
