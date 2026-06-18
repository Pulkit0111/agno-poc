"""Schedule operations behind the Home tab: list (grouped for display), create,
remove, and fire-now. Thin wrappers over the tested ``scheduling`` helpers and the
AgentOS ``ScheduleManager`` — the Home router stays free of scheduling details.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from agno.scheduler.manager import ScheduleManager

from bott.shared.observability.logging_setup import get_logger
from bott.skills import scheduling

from .blocks import band_icon
from .cron import cron_time_12h, cron_to_friendly, default_timezone, format_next_run, to_cron

log = get_logger("bott.slack_home.service")


def _desc(sch: Any) -> dict:
    try:
        return json.loads(getattr(sch, "description", None) or "{}")
    except Exception:  # noqa: BLE001
        return {}


def list_rows(db: Any) -> list[dict]:
    """Display rows for the Home tab. Delivery schedules are one row each; DSM pre/post
    for a team are merged into a single row. Concierge/other schedules are excluded
    (concierge lives in chat, not here)."""
    schedules = ScheduleManager(db).list()
    deliveries: list[tuple[Any, dict]] = []
    security: list[tuple[Any, dict]] = []
    dsm: dict[str, dict[str, tuple[Any, dict]]] = {}

    for s in schedules:
        d = _desc(s)
        name = getattr(s, "name", "") or ""
        kind = d.get("kind") or ("delivery" if name.startswith("delivery-synthesis:") else
                                 "security" if name.startswith("security-digest:") else
                                 "dsm" if name.startswith("dsm-") else "")
        if kind == "delivery":
            deliveries.append((s, d))
        elif kind == "security":
            security.append((s, d))
        elif kind == "dsm":
            team = d.get("label") or name.split(":", 1)[-1]
            phase = d.get("phase") or ("pre" if "precall" in name else "post")
            dsm.setdefault(team, {})[phase] = (s, d)

    rows: list[dict] = []
    for s, d in deliveries:
        nxt = format_next_run(getattr(s, "next_run_at", None), getattr(s, "timezone", "UTC"))
        when = cron_to_friendly(getattr(s, "cron_expr", ""))
        rows.append({
            "icon": band_icon(d.get("band")),
            "label": d.get("label") or getattr(s, "name", "").split(":", 1)[-1],
            "channel": d.get("channel") or "",
            "when": f"{when} · next {nxt}" if nxt else when,
            "run_buttons": [{"text": "▶ Run now", "action_id": f"run_now:{s.id}", "value": s.id}],
            "remove_ids": [s.id],
        })

    for s, d in security:
        nxt = format_next_run(getattr(s, "next_run_at", None), getattr(s, "timezone", "UTC"))
        when = cron_to_friendly(getattr(s, "cron_expr", ""))
        rows.append({
            "icon": "🔒",
            "label": d.get("label") or "Security advisories",
            "channel": d.get("channel") or "",
            "when": f"{when} · next {nxt}" if nxt else when,
            "run_buttons": [{"text": "▶ Run now", "action_id": f"run_now:{s.id}", "value": s.id}],
            "remove_ids": [s.id],
        })

    for team, phases in dsm.items():
        when_parts, run_buttons, remove_ids, channel = [], [], [], ""
        for phase, label in (("pre", "Pre"), ("post", "Post")):
            entry = phases.get(phase)
            if not entry:
                continue
            s, d = entry
            channel = channel or d.get("channel") or ""
            when_parts.append(f"{label} {cron_time_12h(getattr(s, 'cron_expr', ''))}")
            run_buttons.append({"text": f"▶ Run {phase}", "action_id": f"run_now:{s.id}", "value": s.id})
            remove_ids.append(s.id)
        rows.append({
            "icon": "👥", "label": team, "channel": channel,
            "when": " · ".join(when_parts) or "—",
            "run_buttons": run_buttons, "remove_ids": remove_ids,
        })
    return rows


def create_delivery(db: Any, engagement_id: str, account: str, channel: str,
                    frequency: str, time_str: str, band: str | None = None) -> Any:
    return scheduling.create_delivery_synthesis(
        db, engagement_id=engagement_id, channel=channel,
        cron=to_cron(frequency, time_str), timezone=default_timezone(),
        account_name=account, band=band,
    )


def create_security(db: Any, channel: str, frequency: str, time_str: str) -> Any:
    return scheduling.create_security_digest(
        db, channel=channel, cron=to_cron(frequency, time_str), timezone=default_timezone(),
    )


def create_dsm(db: Any, team: str, channel: str, precall_time: str,
               postcall_time: str, days: str) -> None:
    tz = default_timezone()
    scheduling.create_dsm_precall(db, team_id=team, channel=channel,
                                  cron=to_cron(days, precall_time), timezone=tz)
    scheduling.create_dsm_postcall(db, team_id=team, channel=channel,
                                   cron=to_cron(days, postcall_time), timezone=tz)


def remove(db: Any, ids: list[str]) -> None:
    mgr = ScheduleManager(db)
    for sid in ids:
        try:
            mgr.delete(sid)
        except Exception as e:  # noqa: BLE001
            log.error("delete schedule %s failed: %s", sid, e)


def trigger_now(schedule_id: str) -> None:
    """Fire a schedule immediately via the running app's REST endpoint (direct-DB trigger
    is unsupported). Blocks for the run, so callers should run this in the background."""
    port = os.getenv("BOTT_PORT", "7777")
    try:
        httpx.post(f"http://127.0.0.1:{port}/schedules/{schedule_id}/trigger", timeout=180)
    except Exception as e:  # noqa: BLE001
        log.error("trigger %s failed: %s", schedule_id, e)
