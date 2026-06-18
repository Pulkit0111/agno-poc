"""Friendly schedule <-> cron translation (no cron string ever shown to a user)."""

from __future__ import annotations

import pytest

from bott.interfaces.slack_home import cron


def test_to_cron_weekdays():
    assert cron.to_cron("weekdays", "09:00") == "0 9 * * 1-5"


def test_to_cron_daily_and_weekly():
    assert cron.to_cron("daily", "09:30") == "30 9 * * *"
    assert cron.to_cron("weekly", "08:00") == "0 8 * * 1"


def test_to_cron_minutely_ignores_time():
    assert cron.to_cron("minutely", "09:00") == "* * * * *"
    assert cron.cron_to_friendly("* * * * *") == "Every minute"


def test_to_cron_rejects_unknown_frequency():
    with pytest.raises(ValueError):
        cron.to_cron("hourly", "09:00")


def test_to_cron_rejects_bad_time():
    with pytest.raises(ValueError):
        cron.to_cron("daily", "9am")
    with pytest.raises(ValueError):
        cron.to_cron("daily", "25:00")


def test_cron_to_friendly():
    assert cron.cron_to_friendly("0 9 * * 1-5") == "Weekdays 9:00 AM"
    assert cron.cron_to_friendly("30 13 * * *") == "Daily 1:30 PM"
    assert cron.cron_to_friendly("0 8 * * 1") == "Weekly 8:00 AM"


def test_cron_to_friendly_falls_back_on_nonstandard():
    assert cron.cron_to_friendly("*/5 * * * *") == "*/5 * * * *"


def test_cron_time_12h():
    assert cron.cron_time_12h("55 9 * * 1-5") == "9:55 AM"
    assert cron.cron_time_12h("0 0 * * *") == "12:00 AM"


def test_roundtrip_time_formatting():
    assert cron.time_to_12h("00:00") == "12:00 AM"
    assert cron.time_to_12h("12:00") == "12:00 PM"
    assert cron.time_to_12h("23:05") == "11:05 PM"
