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
from .cron import (
    cron_time_12h,
    cron_to_friendly,
    default_timezone,
    format_next_run,
    shift_time,
    to_cron,
)

log = get_logger("bott.slack_home.service")


def _desc(sch: Any) -> dict:
    try:
        return json.loads(getattr(sch, "description", None) or "{}")
    except Exception:  # noqa: BLE001
        return {}


def list_rows(db: Any, viewer_email: str | None = None) -> list[dict]:
    """Display rows for the Home tab. Delivery schedules are one row each; DSM pre/post
    for a team are merged into a single row. Concierge (personal) schedules are excluded
    UNLESS ``viewer_email`` is given, in which case the viewer's OWN concierge schedules
    (and only their own — never another user's) are appended as simple personal cards,
    flagged ``personal`` so blocks can label them accordingly."""
    schedules = ScheduleManager(db).list()
    deliveries: list[tuple[Any, dict]] = []
    security: list[tuple[Any, dict]] = []
    sprints: list[tuple[Any, dict]] = []
    sentiment: list[tuple[Any, dict]] = []
    portfolio: list[tuple[Any, dict]] = []
    dsm: dict[str, dict[str, tuple[Any, dict]]] = {}
    concierge: list[tuple[Any, dict]] = []

    for s in schedules:
        d = _desc(s)
        name = getattr(s, "name", "") or ""
        kind = d.get("kind") or ("delivery" if name.startswith("delivery-synthesis:") else
                                 "security" if name.startswith("security-digest:") else
                                 "sprint" if name.startswith("sprint-report:") else
                                 "sentiment" if name.startswith("sentiment-report:") else
                                 "portfolio" if name.startswith("portfolio-dashboard:") else
                                 "dsm" if name.startswith("dsm-") else
                                 "concierge" if name.startswith("concierge:") else "")
        if kind == "delivery":
            deliveries.append((s, d))
        elif kind == "security":
            security.append((s, d))
        elif kind == "sprint":
            sprints.append((s, d))
        elif kind == "sentiment":
            sentiment.append((s, d))
        elif kind == "portfolio":
            portfolio.append((s, d))
        elif kind == "dsm":
            team = d.get("label") or name.split(":", 1)[-1]
            phase = d.get("phase") or name.split(":", 1)[0].replace("dsm-", "")
            dsm.setdefault(team, {})[phase] = (s, d)
        elif kind == "concierge":
            concierge.append((s, d))

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

    for s, d in sprints:
        nxt = format_next_run(getattr(s, "next_run_at", None), getattr(s, "timezone", "UTC"))
        when = cron_to_friendly(getattr(s, "cron_expr", ""))
        rows.append({
            "icon": "📊",
            "label": d.get("label") or getattr(s, "name", "").split(":", 1)[-1],
            "channel": d.get("channel") or "",  # blank => resolved via Memra at run time
            "when": f"{when} · next {nxt}" if nxt else when,
            "run_buttons": [{"text": "▶ Run now", "action_id": f"run_now:{s.id}", "value": s.id}],
            "remove_ids": [s.id],
        })

    for s, d in sentiment:
        nxt = format_next_run(getattr(s, "next_run_at", None), getattr(s, "timezone", "UTC"))
        when = cron_to_friendly(getattr(s, "cron_expr", ""))
        rows.append({
            "icon": "📈",
            "label": d.get("label") or "Delivery health (portfolio)",
            "channel": d.get("channel") or "",
            "when": f"{when} · next {nxt}" if nxt else when,
            "run_buttons": [{"text": "▶ Run now", "action_id": f"run_now:{s.id}", "value": s.id}],
            "remove_ids": [s.id],
        })

    for s, d in portfolio:
        nxt = format_next_run(getattr(s, "next_run_at", None), getattr(s, "timezone", "UTC"))
        when = cron_to_friendly(getattr(s, "cron_expr", ""))
        rows.append({
            "icon": "🗂️",
            "label": d.get("label") or "Portfolio risk roll-up",
            "channel": d.get("channel") or "",
            "when": f"{when} · next {nxt}" if nxt else when,
            "run_buttons": [{"text": "▶ Run now", "action_id": f"run_now:{s.id}", "value": s.id}],
            "remove_ids": [s.id],
        })

    for team, phases in dsm.items():
        when_parts, run_buttons, remove_ids, channel = [], [], [], ""
        for phase, label in (("open", "Open"), ("preread", "Pre-read"), ("callsummary", "Call summary")):
            entry = phases.get(phase)
            if not entry:
                continue
            s, d = entry
            channel = channel or d.get("channel") or ""
            when_parts.append(f"{label} {cron_time_12h(getattr(s, 'cron_expr', ''))}")
            run_buttons.append({"text": f"▶ {label}", "action_id": f"run_now:{s.id}", "value": s.id})
            remove_ids.append(s.id)
        rows.append({
            "icon": "👥", "label": team, "channel": channel,
            "when": " · ".join(when_parts) or "—",
            "run_buttons": run_buttons, "remove_ids": remove_ids,
        })

    if viewer_email:
        prefix = f"concierge:{viewer_email}:"
        for s, d in concierge:
            name = getattr(s, "name", "") or ""
            if not name.startswith(prefix):
                continue  # never another user's personal schedules
            nxt = format_next_run(getattr(s, "next_run_at", None), getattr(s, "timezone", "UTC"))
            when = cron_to_friendly(getattr(s, "cron_expr", ""))
            label = d.get("label") or name.split(":", 2)[-1] or "Personal task"
            rows.append({
                "icon": "🙋",
                "label": label,
                "channel": "",
                "when": f"{when} · next {nxt}" if nxt else when,
                "run_buttons": [{"text": "▶ Run now", "action_id": f"run_now:{s.id}", "value": s.id}],
                "remove_ids": [s.id],
                "personal": True,
            })
    return rows


def _parse_iso(value: str | None):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def sprint_end_info(engagement_key: str) -> dict | None:
    """For the modal: the engagement's current (or latest) sprint end date, as a friendly
    label plus the cron weekday to pin the schedule to. None if Jira can't resolve it."""
    from .cron import weekday_to_cron_dow

    try:
        from bott.skills.sprint_report.tool import _jira

        client = _jira()
        board = client.find_board(engagement_key)
        if board is None:
            return None
        sprint = client.active_sprint(board["id"]) or client.latest_closed_sprint(board["id"])
        if not sprint:
            return None
    except Exception as e:  # noqa: BLE001 — modal must not break on a Jira hiccup
        log.error("sprint_end_info failed for %s: %s", engagement_key, e)
        return None

    end = _parse_iso(sprint.get("end"))
    if end is None:
        return None
    label = f"Current sprint ends {end.strftime('%a, %-d %b')}"
    start = _parse_iso(sprint.get("start"))
    if start:
        weeks = max(1, round((end - start).days / 7))
        label += f" · ~{weeks}-week cadence"
    return {"label": label, "cron_dow": weekday_to_cron_dow(end.weekday())}


def create_sprint_report_schedule(db: Any, engagement_key: str, channel: str, time_str: str,
                                  created_by: str | None = None) -> Any:
    """Create the per-engagement sprint-report schedule, pinned to the sprint's end weekday
    (falls back to Friday if Jira can't tell us) at the chosen time."""
    from .cron import to_cron_weekday

    info = sprint_end_info(engagement_key)
    cron_dow = info["cron_dow"] if info else 5  # Friday default
    return scheduling.create_sprint_report(
        db, engagement=engagement_key, cron=to_cron_weekday(cron_dow, time_str),
        timezone=default_timezone(), channel=channel, created_by=created_by,
    )


def create_delivery(db: Any, engagement_id: str, account: str, channel: str,
                    frequency: str, time_str: str, band: str | None = None,
                    created_by: str | None = None) -> Any:
    return scheduling.create_delivery_synthesis(
        db, engagement_id=engagement_id, channel=channel,
        cron=to_cron(frequency, time_str), timezone=default_timezone(),
        account_name=account, band=band, created_by=created_by,
    )


def create_security(db: Any, channel: str, frequency: str, time_str: str,
                    created_by: str | None = None) -> Any:
    return scheduling.create_security_digest(
        db, channel=channel, cron=to_cron(frequency, time_str), timezone=default_timezone(),
        created_by=created_by,
    )


def create_sentiment(db: Any, channel: str, frequency: str, time_str: str,
                     created_by: str | None = None) -> Any:
    return scheduling.create_sentiment_report(
        db, channel=channel, cron=to_cron(frequency, time_str), timezone=default_timezone(),
        created_by=created_by,
    )


def create_portfolio(db: Any, channel: str, frequency: str, time_str: str,
                     created_by: str | None = None) -> Any:
    return scheduling.create_portfolio_dashboard(
        db, channel=channel, cron=to_cron(frequency, time_str), timezone=default_timezone(),
        created_by=created_by,
    )


def create_dsm(db: Any, team: str, channel: str, call_time: str, open_offset_min: int,
               close_offset_min: int, postcall_time: str, days: str,
               created_by: str | None = None) -> Any:
    """Three derived schedules: open (call − open_offset), pre-read (call − close_offset),
    and the post-call summary (at postcall_time). Returns the 'open' schedule (the merged
    Home/console row is keyed by team name, so any one of the three ids works as a handle)."""
    tz = default_timezone()
    open_sch = scheduling.create_dsm_open(
        db, team_id=team, channel=channel,
        cron=to_cron(days, shift_time(call_time, open_offset_min)), timezone=tz,
        created_by=created_by,
    )
    scheduling.create_dsm_preread(db, team_id=team, channel=channel,
                                  cron=to_cron(days, shift_time(call_time, close_offset_min)), timezone=tz,
                                  created_by=created_by)
    scheduling.create_dsm_callsummary(db, team_id=team, channel=channel,
                                      cron=to_cron(days, postcall_time), timezone=tz,
                                      created_by=created_by)
    return open_sch


def create_dsm_default(db: Any, team: str, channel: str, call_time: str, *, days: str = "weekdays",
                       created_by: str | None = None) -> Any:
    """Console-facing DSM creation: the same three-schedule shape the Slack modal builds,
    with the modal's own default offsets (open 2h before, pre-read 1h before) and a
    post-call summary 30 min after — the console form only asks for team + channel + call
    time, so it delegates to `create_dsm` with those defaults filled in."""
    return create_dsm(db, team, channel, call_time, 120, 60, shift_time(call_time, -30), days,
                      created_by=created_by)


def schedule_owner(row_or_description: Any) -> str | None:
    """Best-effort creator email for a schedule: the description JSON's ``created_by``
    field, else the legacy ``concierge:{email}:...`` name convention (schedules created
    before ``created_by`` was stamped, or by the chat `create_schedule` tool), else None —
    a bare None means a legacy org-wide row with no recoverable owner, which callers treat
    as admin-only.

    Accepts either a raw ``ScheduleManager`` ``Schedule`` row (object with ``.description``
    + ``.name``) or an equivalent dict (``{"description": ..., "name": ...}``), or the
    already-parsed description dict itself.
    """
    if row_or_description is None:
        return None
    if isinstance(row_or_description, dict):
        name = row_or_description.get("name", "") or ""
        if "description" in row_or_description:
            try:
                desc = json.loads(row_or_description.get("description") or "{}")
            except (TypeError, ValueError):
                desc = {}
        else:
            # already the parsed description dict
            desc = row_or_description
    else:
        desc = _desc(row_or_description)
        name = getattr(row_or_description, "name", "") or ""
    created_by = desc.get("created_by")
    if created_by:
        return created_by
    if name.startswith("concierge:"):
        parts = name.split(":", 2)
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return None


def schedule_owner_for_id(db: Any, schedule_id: str) -> str | None:
    """`schedule_owner`, looked up by id — the shape the console's owner-or-admin gate
    needs (it only has the id from the URL, not the row)."""
    sch = ScheduleManager(db).get(schedule_id)
    if sch is None:
        return None
    return schedule_owner(sch)


def cadence_text(cron: str, timezone: str = "UTC") -> str:
    """Plain-language cadence for a cron expression — wraps `cron_to_friendly`.
    ``timezone`` is accepted (not yet used in the phrasing) so callers don't need a
    separate helper if this grows timezone-aware wording later."""
    return cron_to_friendly(cron)


def preview(frequency: str, time_str: str) -> dict:
    """Preview a not-yet-created schedule's cadence + next fire time, computed the same
    way an actual schedule would be (``to_cron`` + the AgentOS scheduler's own
    `compute_next_run`, which is exactly what backs `list_raw`'s ``next_run``) — no DB
    write involved."""
    from agno.scheduler.cron import compute_next_run

    cron = to_cron(frequency, time_str)
    tz = default_timezone()
    next_epoch = compute_next_run(cron, tz)
    return {"next_run": format_next_run(next_epoch, tz), "cadence": cadence_text(cron, tz)}


def list_raw(db: Any, viewer_email: str | None = None,
             include_all_personal: bool = False) -> list[dict]:
    """One row per raw Schedule — unlike list_rows(), which merges related schedules
    (e.g. DSM's 3 phases) into one display card, this is the 1:1 view the console needs
    for pause/resume/remove-by-id.

    Personal (``concierge:``) rows are private: only the viewer's own are included
    (matched via `schedule_owner` against ``viewer_email``), unless
    ``include_all_personal`` is set (admin view). Team rows are always visible to
    everyone. With neither argument (the default), no personal rows appear at all —
    the safe baseline for callers that don't identify a viewer."""
    mgr = ScheduleManager(db)
    rows = []
    for sch in mgr.list():
        try:
            meta = json.loads(sch.description or "{}")
        except (TypeError, ValueError):
            meta = {}
        personal = sch.name.startswith("concierge:")
        if personal and not include_all_personal:
            owner = schedule_owner(sch)
            if not viewer_email or not owner or owner.lower() != viewer_email.lower():
                continue
        rows.append({
            "id": sch.id,
            "label": meta.get("label", sch.name),
            "kind": meta.get("kind", ""),
            "channel": meta.get("channel", ""),
            "cron": sch.cron_expr,
            "timezone": sch.timezone,
            "enabled": sch.enabled,
            "next_run": format_next_run(sch.next_run_at, sch.timezone),
            "cadence": cadence_text(sch.cron_expr, sch.timezone),
            "created_by": schedule_owner(sch),
            "personal": personal,
        })
    return rows


def pause(db: Any, schedule_id: str) -> bool:
    return ScheduleManager(db).disable(schedule_id) is not None


def resume(db: Any, schedule_id: str) -> bool:
    return ScheduleManager(db).enable(schedule_id) is not None


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
