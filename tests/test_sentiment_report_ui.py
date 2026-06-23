"""App Home wiring for the portfolio sentiment / delivery-health digest."""

from __future__ import annotations

from agno.db.sqlite import SqliteDb

from bott.interfaces.slack_home import blocks, router, service


def test_sentiment_modal_shape():
    m = blocks.build_sentiment_modal()
    assert m["callback_id"] == "create_sentiment"
    block_ids = {b.get("block_id") for b in m["blocks"]}
    assert {"channel", "frequency", "time"} <= block_ids
    assert "portfolio" in str(m).lower()


def test_add_sentiment_button_on_home():
    view = blocks.build_home_view([])
    assert "add_sentiment" in str(view)


def test_submit_sentiment_creates_schedule(monkeypatch):
    captured = {}
    monkeypatch.setattr(service, "create_sentiment",
                        lambda db, channel, frequency, time_str: captured.update(
                            {"channel": channel, "frequency": frequency, "time": time_str}))
    values = {
        "channel": {"v": {"selected_channel": "C42"}},
        "frequency": {"v": {"selected_option": {"value": "weekly"}}},
        "time": {"v": {"selected_time": "09:00"}},
    }
    router._submit_sentiment(None, values)
    assert captured == {"channel": "C42", "frequency": "weekly", "time": "09:00"}


def test_sentiment_schedule_shows_in_home_rows(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    service.create_sentiment(db, "C42", "weekly", "09:00")
    rows = service.list_rows(db)
    row = next(r for r in rows if r["icon"] == "📈")
    assert "Delivery health" in row["label"]
    assert row["run_buttons"] and row["remove_ids"]
