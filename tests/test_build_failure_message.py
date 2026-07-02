"""Build-failure messages must state a cause + a next step, and never leak internal plumbing."""

from __future__ import annotations

from bott.interfaces.slack_app import build_failure_message

_LEAKS = ("queued", "git push", "traceback", "stderr", "local git", "build flow", "worker")


def _assert_no_leak(msg: str) -> None:
    low = msg.lower()
    for leak in _LEAKS:
        assert leak not in low, f"message leaked internal term '{leak}': {msg}"


def test_write_access_failure_names_the_fix():
    msg = build_failure_message(
        "o", "r", "git push failed: remote: Write access to repository not granted.\n403")
    assert "write" in msg.lower()
    assert "contents: write" in msg.lower() or "admin" in msg.lower()
    _assert_no_leak(msg)


def test_network_failure_reads_as_transient():
    msg = build_failure_message("o", "r", "fatal: unable to access: Could not resolve host: github.com")
    assert "again" in msg.lower()
    _assert_no_leak(msg)


def test_not_found_points_at_installation():
    msg = build_failure_message("o", "r", "404 Not Found")
    assert "install" in msg.lower() or "find" in msg.lower()
    _assert_no_leak(msg)


def test_default_is_short_and_actionable():
    msg = build_failure_message("o", "r", "some obscure failure\nsecond line with detail")
    assert "o/r" in msg
    assert "try again" in msg.lower()
    assert "second line" not in msg  # only the first line, capped
    _assert_no_leak(msg)
