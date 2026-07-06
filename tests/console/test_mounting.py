"""The mounting rule, tested without booting the whole AgentOS app: the helper
decides from env whether the console router should mount."""
import pytest

from bott.interfaces.console.router import should_mount_console


def test_mounts_when_secret_set(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "x")
    assert should_mount_console() is True


def test_skips_without_secret(monkeypatch):
    monkeypatch.delenv("CONSOLE_SESSION_SECRET", raising=False)
    assert should_mount_console() is False
