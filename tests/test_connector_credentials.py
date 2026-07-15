# tests/test_connector_credentials.py
"""Round-trip + isolation tests for the console-added connector credential store.

Fixture pattern: a fresh SQLite file + BOTT_SECRET_KEY
per test, schema initialized once via schema.init_schema()."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from bott.shared import connector_credentials as cc
from bott.shared import db


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "cc.db"))
    monkeypatch.setenv("BOTT_SECRET_KEY", __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    yield


def test_load_missing_returns_none(store):
    assert cc.load("github-app") is None


def test_store_then_load_round_trips(store):
    cc.store("github-app", {"app_id": "123", "installation_id": "456", "private_key": "PEM"})
    assert cc.load("github-app") == {"app_id": "123", "installation_id": "456", "private_key": "PEM"}


def test_ciphertext_at_rest_is_not_plaintext(store):
    """The whole point of the store is encryption at rest — assert the DB row itself
    never contains the plaintext secret."""
    cc.store("sentry-secondorg", {"org": "secondorg", "auth_token": "super-secret-token", "base_url": "https://sentry.io"})
    with db.get_engine().connect() as c:
        row = c.execute(text(
            "SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"
        ), {"u": "connector-config", "p": "sentry-secondorg"}).fetchone()
    assert row is not None
    assert "super-secret-token" not in row[0]
    assert "secondorg" not in row[0] or row[0] != "secondorg"  # ciphertext, not a bare copy


def test_store_overwrites_existing(store):
    cc.store("http-foo", {"base_url": "https://a.example.com"})
    cc.store("http-foo", {"base_url": "https://b.example.com"})
    assert cc.load("http-foo") == {"base_url": "https://b.example.com"}


def test_remove_deletes(store):
    cc.store("http-foo", {"base_url": "https://a.example.com"})
    cc.remove("http-foo")
    assert cc.load("http-foo") is None


def test_remove_unknown_is_a_no_op(store):
    cc.remove("not-there")  # must not raise


def test_configured_names_lists_all_stored(store):
    assert cc.configured_names() == []
    cc.store("github-app", {"app_id": "1", "installation_id": None, "private_key": "pem"})
    cc.store("sentry-secondorg", {"org": "secondorg", "auth_token": "t", "base_url": "https://sentry.io"})
    assert cc.configured_names() == ["github-app", "sentry-secondorg"]


def test_name_is_case_insensitive_and_trimmed(store):
    cc.store("  HTTP-Foo  ", {"base_url": "https://a.example.com"})
    assert cc.load("http-foo") == {"base_url": "https://a.example.com"}
    assert cc.configured_names() == ["http-foo"]


def test_store_rejects_empty_name(store):
    with pytest.raises(ValueError):
        cc.store("", {"base_url": "https://a.example.com"})


def test_codex_is_not_a_store_backed_name(store):
    """Codex auth lives in CODEX_HOME (the CLI's own store), never in connector_tokens —
    'codex' must not resolve, list, or delete anything here."""
    assert cc.load("codex") is None
    assert "codex" not in cc.configured_names()
    cc.remove("codex")  # no-op


def test_load_tolerates_missing_table(monkeypatch, tmp_path):
    """A fresh/pre-migration DB with no connector_tokens table must not crash config
    reads that fall through this store as an optional overlay — it just means
    'nothing stored', not an error."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "no-schema.db"))
    db.get_engine(fresh=True)
    assert cc.load("github-app") is None
    assert cc.configured_names() == []
