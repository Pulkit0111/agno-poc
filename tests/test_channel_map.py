"""Channel→engagement mapping so 'this engagement' resolves in-channel (Bassam: 'Map this
channel to Ironman' used to be a hard refusal)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bott.shared import db
from bott.skills import channel_map as cm


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "cm.db"))
    monkeypatch.setenv("BOTT_SECRET_KEY",
                       __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    yield


def _ctx(channel):
    return SimpleNamespace(dependencies={"Slack channel_id": channel}, user_id="u@x.com")


def test_map_then_resolve(store):
    assert "Ironman" in cm._map_impl(_ctx("C1"), "Ironman")
    assert cm._resolve_impl(_ctx("C1")) == "Ironman"


def test_resolve_empty_when_unmapped(store):
    assert cm._resolve_impl(_ctx("C-none")) == ""


def test_mapping_is_per_channel(store):
    cm._map_impl(_ctx("C1"), "Ironman")
    cm._map_impl(_ctx("C2"), "PADI")
    assert cm._resolve_impl(_ctx("C1")) == "Ironman"
    assert cm._resolve_impl(_ctx("C2")) == "PADI"


def test_map_needs_channel_and_engagement(store):
    assert "channel" in cm._map_impl(SimpleNamespace(dependencies={}), "Ironman").lower()
    assert "which engagement" in cm._map_impl(_ctx("C1"), "  ").lower()


def test_unmap_clears(store):
    cm._map_impl(_ctx("C1"), "Ironman")
    cm._unmap_impl(_ctx("C1"))
    assert cm._resolve_impl(_ctx("C1")) == ""


def test_tools_exposed():
    names = {t.name for t in cm.channel_map_tools()}
    assert {"map_channel_to_engagement", "channel_engagement", "unmap_channel_engagement"} <= names


def test_list_all_excludes_unmapped(store):
    from bott.shared.persistence.records import set_setting
    set_setting(cm._KEY.format("C111"), "acme-commerce")
    set_setting(cm._KEY.format("C222"), "")  # unmapped
    rows = cm.list_all()
    assert rows == [{"channel_id": "C111", "engagement": "acme-commerce"}]


def test_list_settings_by_prefix_scoped_correctly(store):
    from bott.shared.persistence.records import list_settings_by_prefix, set_setting
    set_setting("channel_engagement:C1", "acme")
    set_setting("other_prefix:C1", "unrelated")
    rows = list_settings_by_prefix("channel_engagement:")
    assert rows == {"channel_engagement:C1": "acme"}


def test_list_settings_by_prefix_is_wildcard_safe(store):
    """`_` in a prefix is a SQL LIKE wildcard (matches any single char) — a prefix like
    "a_b:" would SQL-LIKE-match a key like "axbc:x" even though it isn't a real prefix
    match. The Python-side startswith re-check must exclude it."""
    from bott.shared.persistence.records import list_settings_by_prefix, set_setting
    set_setting("axbc:x", "should-not-match")
    set_setting("a_b:x", "should-match")
    rows = list_settings_by_prefix("a_b:")
    assert rows == {"a_b:x": "should-match"}
