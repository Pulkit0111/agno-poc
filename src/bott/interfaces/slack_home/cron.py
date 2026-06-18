"""Friendly schedule <-> cron translation.

No cron string ever reaches a user: the Home UI speaks Daily / Weekdays / Weekly + a
time, and everything is translated here. Kept pure (no I/O) so it's directly testable.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Friendly frequency -> cron day-of-week field. "weekly" means Mondays.
_FREQ_TO_DOW = {"daily": "*", "weekdays": "1-5", "weekly": "1"}
# Reverse, for display.
_DOW_TO_LABEL = {"*": "Daily", "1-5": "Weekdays", "1": "Weekly"}

# "Every minute" — a demo frequency so you can add a schedule and watch the poller
# (15s tick) fire it within ~a minute, unattended. The time field is ignored.
_EVERY_MINUTE = "* * * * *"


def default_timezone() -> str:
    """Timezone new schedules are created in (override via BOTT_TIMEZONE)."""
    return os.getenv("BOTT_TIMEZONE", "Asia/Kolkata")


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    parts = (time_str or "").split(":")
    if len(parts) != 2:
        raise ValueError(f"bad time {time_str!r} (want 'HH:MM')")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"time out of range: {time_str!r}")
    return hh, mm


def to_cron(frequency: str, time_str: str) -> str:
    """('weekdays', '09:00') -> '0 9 * * 1-5'. 'minutely' -> '* * * * *' (time ignored)."""
    freq = (frequency or "").strip().lower()
    if freq == "minutely":
        return _EVERY_MINUTE
    hh, mm = _parse_hhmm(time_str)
    dow = _FREQ_TO_DOW.get(freq)
    if dow is None:
        raise ValueError(f"unknown frequency: {frequency!r}")
    return f"{mm} {hh} * * {dow}"


def time_to_12h(time_str: str) -> str:
    """'13:30' -> '1:30 PM'."""
    hh, mm = _parse_hhmm(time_str)
    suffix = "AM" if hh < 12 else "PM"
    return f"{hh % 12 or 12}:{mm:02d} {suffix}"


def cron_time_12h(cron: str) -> str:
    """Just the time portion of a cron: '55 9 * * 1-5' -> '9:55 AM'."""
    parts = (cron or "").split()
    if len(parts) != 5:
        return cron or "?"
    try:
        return time_to_12h(f"{int(parts[1]):02d}:{int(parts[0]):02d}")
    except ValueError:
        return cron


def shift_time(time_str: str, minus_minutes: int) -> str:
    """'10:00' shifted back 120 min -> '08:00' (wraps within a day). Used to derive the
    open/pre-read cron times from the standup call time minus a configurable offset."""
    hh, mm = _parse_hhmm(time_str)
    total = (hh * 60 + mm - int(minus_minutes)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def cron_to_friendly(cron: str) -> str:
    """'0 9 * * 1-5' -> 'Weekdays 9:00 AM'. Falls back to the raw cron if non-standard."""
    if (cron or "").strip() == _EVERY_MINUTE:
        return "Every minute"
    parts = (cron or "").split()
    if len(parts) != 5:
        return cron or "?"
    mm, hh, _, _, dow = parts
    try:
        when = time_to_12h(f"{int(hh):02d}:{int(mm):02d}")
    except ValueError:
        return cron
    return f"{_DOW_TO_LABEL.get(dow, dow)} {when}"


def format_next_run(epoch: int | None, timezone: str = "UTC") -> str:
    """A friendly 'next run' label from a unix timestamp, in the schedule's timezone.
    Returns '' if unknown so callers can omit it."""
    if not epoch:
        return ""
    try:
        dt = datetime.fromtimestamp(int(epoch), ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 — bad tz/epoch -> just omit
        return ""
    return dt.strftime("%b %-d, %-I:%M %p")
