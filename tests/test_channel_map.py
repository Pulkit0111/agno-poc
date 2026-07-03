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
