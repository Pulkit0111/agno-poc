"""Deterministic tests for the Codex proxy manager + backend selection (no subprocess)."""

from __future__ import annotations

import pytest

from bott.shared import codex
from bott.shared.codex import CodexProxyManager, start_model_backend


def test_base_url():
    assert CodexProxyManager(port=12345).base_url == "http://127.0.0.1:12345/v1"


def test_is_ready_false_when_down():
    # Nothing is listening on this port → not ready (fast failure, no spawn).
    assert CodexProxyManager(port=59999).is_ready(timeout=1.0) is False


def test_should_respawn_spares_alive_proxy_but_replaces_crashed():
    # A crashed (exited) proxy is replaced quickly...
    assert CodexProxyManager._should_respawn(2, proc_alive=False) is True
    assert CodexProxyManager._should_respawn(1, proc_alive=False) is False
    # ...but an alive-but-slow proxy is NOT nuked on a few missed health checks (the bug:
    # a transient slow /v1/models used to kill a working proxy and cause real downtime).
    assert CodexProxyManager._should_respawn(3, proc_alive=True) is False
    assert CodexProxyManager._should_respawn(23, proc_alive=True) is False
    # Only a long sustained unreachability (truly hung) forces a respawn.
    assert CodexProxyManager._should_respawn(24, proc_alive=True) is True


def test_start_errors_clearly_without_codex_login(monkeypatch):
    mgr = CodexProxyManager(port=59999)
    monkeypatch.setattr(mgr, "is_ready", lambda timeout=3.0: False)
    monkeypatch.setattr(codex.os.path, "exists", lambda p: False)
    with pytest.raises(RuntimeError, match="codex login"):
        mgr.start(wait_seconds=1)


def test_openai_backend_clears_proxy_urls(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "openai")
    monkeypatch.setenv("REVIEW_MODEL_BASE_URL", "http://stale:10531/v1")
    monkeypatch.setenv("MANAGER_MODEL_BASE_URL", "http://stale:10531/v1")
    mgr = start_model_backend()
    assert mgr is None
    assert "REVIEW_MODEL_BASE_URL" not in codex.os.environ
    assert "MANAGER_MODEL_BASE_URL" not in codex.os.environ


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "bogus")
    with pytest.raises(RuntimeError, match="Unknown MODEL_BACKEND"):
        start_model_backend()
