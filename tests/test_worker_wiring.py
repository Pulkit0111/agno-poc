"""Guard the bott-app worker wiring (app.main): the handler + queue primitives it needs
must stay importable. Regression guard — a refactor once let ruff strip these."""

from __future__ import annotations


def test_worker_wiring_symbols_resolve(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)  # importable without a real token
    from bott.interfaces.slack_app import handle_task
    from bott.shared.persistence import store

    assert callable(handle_task)
    assert callable(store.init_db)
    assert callable(store.recover_orphans)
    assert callable(store.Worker)
