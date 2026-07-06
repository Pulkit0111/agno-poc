"""Runtime overrides for action_policy.classify() — KV-backed (settings table), the exact
primitives Plans 1/3 already built (get_setting/set_setting/list_settings_by_prefix). An
override is soft-deleted by setting its value to empty string, same convention channel_map.py
already uses — list_overrides() filters those out."""

from __future__ import annotations

import json
import time

_BASE = "policy_override"
_PREFIX = _BASE + ":{}:{}"
_VALID_VERDICTS = {"allow", "gate", "deny"}


def set_override(system: str, method: str, verdict: str, reason: str, updated_by: str) -> None:
    if verdict not in _VALID_VERDICTS:
        raise ValueError(f"Unknown verdict: {verdict!r} — must be one of {sorted(_VALID_VERDICTS)}")
    from bott.shared.persistence.records import set_setting
    value = json.dumps({
        "verdict": verdict, "reason": reason, "updated_by": updated_by, "updated_at": time.time(),
    })
    set_setting(_PREFIX.format(system.lower(), method.lower()), value)


def remove_override(system: str, method: str) -> None:
    from bott.shared.persistence.records import set_setting
    set_setting(_PREFIX.format(system.lower(), method.lower()), "")


def get_override(system: str, method: str) -> dict | None:
    from bott.shared.persistence.records import get_setting
    raw = get_setting(_PREFIX.format(system.lower(), method.lower()))
    if not raw:
        return None
    return json.loads(raw)


def list_overrides() -> list[dict]:
    from bott.shared.persistence.records import list_settings_by_prefix
    rows = list_settings_by_prefix(f"{_BASE}:")
    out = []
    for key, value in rows.items():
        if not value:
            continue
        _, system, method = key.split(":", 2)
        data = json.loads(value)
        out.append({"system": system, "method": method, **data})
    return out
