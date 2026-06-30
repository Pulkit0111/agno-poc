"""FastAPI routes for the Slack App Home control panel.

Two endpoints, both signed by Slack:

- ``POST /slack/events`` — the single Events URL. Handles the url_verification handshake
  and ``app_home_opened`` (renders the Home tab); forwards every other event (DMs,
  mentions) verbatim to Agno's chat interface at ``/slack/chat/events`` so the chat UX is
  untouched.
- ``POST /slack/interactivity`` — the Interactivity URL. Handles the Home buttons
  (Add / Run now / Remove) and the modal submissions.
"""

from __future__ import annotations

import json
import os

import httpx
from agno.os.interfaces.slack.security import verify_slack_signature
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from slack_sdk import WebClient

from bott.shared import approvals
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import queue, standup
from bott.skills.dsm import today_key

from . import blocks, service
from .engagements import engagement_shortlist, sprint_board_options_with_reason

log = get_logger("bott.slack_home.router")

# Headers Slack signs; forwarded unchanged so Agno's own signature check still passes.
_FWD_HEADERS = {
    "content-type", "x-slack-signature", "x-slack-request-timestamp",
    "x-slack-retry-num", "x-slack-retry-reason",
}


def build_slack_home_router(db, token: str, signing_secret: str, *, chat_prefix: str = "/slack/chat") -> APIRouter:
    router = APIRouter(tags=["Slack Home"])
    client = WebClient(token=token)

    def _verify(body: bytes, request: Request) -> None:
        ts = request.headers.get("X-Slack-Request-Timestamp")
        sig = request.headers.get("X-Slack-Signature", "")
        if not ts or not sig:
            raise HTTPException(status_code=400, detail="Missing Slack headers")
        if not verify_slack_signature(body, ts, sig, signing_secret=signing_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

    def publish_home(user_id: str | None) -> None:
        if not user_id:
            return
        try:
            client.views_publish(user_id=user_id, view=blocks.build_home_view(service.list_rows(db)))
        except Exception as e:  # noqa: BLE001
            log.error("home publish failed for %s: %s", user_id, e)

    def run_now(user_id: str | None, schedule_id: str | None) -> None:
        if not schedule_id:
            return
        try:
            if user_id:
                client.chat_postMessage(
                    channel=user_id,
                    text="⏳ Running that now — the digest will post to its channel shortly.",
                )
        except Exception:  # noqa: BLE001 — feedback DM is best-effort
            pass
        service.trigger_now(schedule_id)

    def fill_delivery_modal(view_id: str) -> None:
        """Fetch the Memra engagement shortlist and swap it into the already-open modal.
        Done after open (keyed by view_id, not the short-lived trigger_id)."""
        try:
            client.views_update(view_id=view_id,
                                view=blocks.build_delivery_modal(engagement_shortlist()))
        except Exception as e:  # noqa: BLE001
            log.error("fill delivery modal failed: %s", e)

    def fill_sprint_modal(view_id: str) -> None:
        """Swap the Jira board list into the already-open sprint-report modal (or show why
        it's empty: not configured / unreachable / no boards)."""
        try:
            options, reason = sprint_board_options_with_reason()
            client.views_update(view_id=view_id,
                                view=blocks.build_sprint_modal(options, empty_reason=reason))
        except Exception as e:  # noqa: BLE001
            log.error("fill sprint modal failed: %s", e)

    def show_sprint_end(view_id: str, key: str, channel: str | None, time_str: str) -> None:
        """After the user picks an engagement, fetch its sprint end date from Jira and
        re-render the modal with that date shown (preserving channel/time already entered)."""
        try:
            info = service.sprint_end_info(key)
            options, _ = sprint_board_options_with_reason()
            client.views_update(
                view_id=view_id,
                view=blocks.build_sprint_modal(
                    options, selected_key=key,
                    sprint_end_label=(info or {}).get("label")
                    or "Couldn't read this engagement's sprint dates — will default to Fridays.",
                    channel=channel, time_initial=time_str or "17:00",
                ),
            )
        except Exception as e:  # noqa: BLE001
            log.error("show sprint end failed for %s: %s", key, e)

    async def forward_to_chat(body: bytes, headers) -> Response:
        port = os.getenv("BOTT_PORT", "7777")
        url = f"http://127.0.0.1:{port}{chat_prefix}/events"
        fwd = {k: v for k, v in headers.items() if k.lower() in _FWD_HEADERS}
        async with httpx.AsyncClient() as c:
            r = await c.post(url, content=body, headers=fwd, timeout=30)
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

    @router.post("/slack/events", name="slack_home_events")
    async def slack_events(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        _verify(body, request)
        data = json.loads(body or b"{}")
        if data.get("type") == "url_verification":
            return {"challenge": data.get("challenge")}
        event = data.get("event") or {}
        if event.get("type") == "app_home_opened":
            background_tasks.add_task(publish_home, event.get("user"))
            return {"ok": True}
        # Not a Home event — hand chat (DMs, mentions) to Agno's interface unchanged.
        return await forward_to_chat(body, request.headers)

    @router.post("/slack/interactivity", name="slack_home_interactivity")
    async def slack_interactivity(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        _verify(body, request)
        form = await request.form()
        raw = form.get("payload")
        if not isinstance(raw, str) or not raw:
            raise HTTPException(status_code=400, detail="Missing payload")
        payload = json.loads(raw)
        ptype = payload.get("type")
        user_id = (payload.get("user") or {}).get("id")

        if ptype == "block_actions":
            action = (payload.get("actions") or [{}])[0]
            cmd = (action.get("action_id") or "").split(":", 1)[0]
            trigger_id = payload.get("trigger_id")
            if cmd == "add_delivery":
                try:
                    # Open instantly with a placeholder (no Memra in the 3s trigger window),
                    # then fill the engagement list via views.update keyed by view_id.
                    resp = client.views_open(
                        trigger_id=trigger_id,
                        view=blocks.build_delivery_modal([], loading=True),
                    )
                    view_id = (resp.get("view") or {}).get("id")
                    if view_id:
                        background_tasks.add_task(fill_delivery_modal, view_id)
                except Exception as e:  # noqa: BLE001
                    log.error("open delivery modal: %s", e)
            elif cmd == "add_dsm":
                try:
                    client.views_open(trigger_id=trigger_id, view=blocks.build_dsm_modal())
                except Exception as e:  # noqa: BLE001
                    log.error("open dsm modal: %s", e)
            elif cmd == "add_security":
                try:
                    client.views_open(trigger_id=trigger_id, view=blocks.build_security_modal())
                except Exception as e:  # noqa: BLE001
                    log.error("open security modal: %s", e)
            elif cmd == "add_sentiment":
                try:
                    client.views_open(trigger_id=trigger_id, view=blocks.build_sentiment_modal())
                except Exception as e:  # noqa: BLE001
                    log.error("open sentiment modal: %s", e)
            elif cmd == "add_portfolio":
                try:
                    client.views_open(trigger_id=trigger_id, view=blocks.build_portfolio_modal())
                except Exception as e:  # noqa: BLE001
                    log.error("open portfolio modal: %s", e)
            elif cmd == "add_sprint":
                try:
                    resp = client.views_open(trigger_id=trigger_id,
                                             view=blocks.build_sprint_modal([], loading=True))
                    view_id = (resp.get("view") or {}).get("id")
                    if view_id:
                        background_tasks.add_task(fill_sprint_modal, view_id)
                except Exception as e:  # noqa: BLE001
                    log.error("open sprint modal: %s", e)
            elif cmd == "sprint_eng_selected":
                # User picked an engagement — fetch its sprint end date and re-render the modal.
                view = payload.get("view") or {}
                view_id = view.get("id")
                key = (action.get("selected_option") or {}).get("value")
                vals = view.get("state", {}).get("values", {})
                channel = (vals.get("channel") or {}).get("v", {}).get("selected_channel")
                time_str = (vals.get("time") or {}).get("v", {}).get("selected_time") or "17:00"
                if view_id and key and key != "none":
                    background_tasks.add_task(show_sprint_end, view_id, key, channel, time_str)
            elif cmd == "add_standup_update":
                try:
                    client.views_open(trigger_id=trigger_id,
                                      view=blocks.build_standup_modal(action.get("value") or "", today_key()))
                except Exception as e:  # noqa: BLE001
                    log.error("open standup modal: %s", e)
            elif cmd == "run_now":
                background_tasks.add_task(run_now, user_id, action.get("value"))
            elif cmd == "remove":
                ids = [i for i in (action.get("value") or "").split(",") if i]
                service.remove(db, ids)
                background_tasks.add_task(publish_home, user_id)
            elif cmd == "rereview_pr":
                # The "Re-review" button on a posted review — re-run against the prior
                # trace for this thread (the worker looks it up by channel + thread_ts).
                ch = (payload.get("channel") or {}).get("id")
                msg = payload.get("message") or {}
                thread_ts = msg.get("thread_ts") or msg.get("ts")
                if ch and thread_ts:
                    queue.enqueue("rereview", {"channel": ch, "thread_ts": thread_ts,
                                               "trigger_ts": None, "reply_text": "(manual re-review requested)"},
                                  user_id=user_id or "system@axelerant.com")
            elif cmd in ("approval_approve", "approval_dismiss"):
                # Approve/Dismiss buttons surface when the agent needs human sign-off.
                # action_id carries the decision; value carries the approval id.
                approval_id_str = action.get("value") or ""
                ch = (payload.get("channel") or {}).get("id")
                msg = payload.get("message") or {}
                thread_ts = msg.get("thread_ts") or msg.get("ts")
                if approval_id_str and user_id:
                    try:
                        approvals.decide(
                            int(approval_id_str),
                            approved=(cmd == "approval_approve"),
                            decided_by=user_id,
                        )
                        if cmd == "approval_approve":
                            dispatch_approved_build(int(approval_id_str))
                        decision_label = "approved" if cmd == "approval_approve" else "dismissed"
                        if ch:
                            try:
                                client.chat_postMessage(
                                    channel=ch,
                                    thread_ts=thread_ts,
                                    text=f"<@{user_id}> {decision_label} this request.",
                                )
                            except Exception:  # noqa: BLE001 — confirmation DM is best-effort
                                pass
                    except Exception as e:  # noqa: BLE001
                        log.error("approval decision failed (id=%s): %s", approval_id_str, e)
            return {"ok": True}

        if ptype == "view_submission":
            view = payload.get("view") or {}
            cb = view.get("callback_id")
            values = view.get("state", {}).get("values", {})
            # A standup update isn't a schedule — store it, don't refresh the Home tab.
            if cb == "submit_standup":
                try:
                    _submit_standup(view, payload.get("user") or {})
                except Exception as e:  # noqa: BLE001
                    log.error("standup submission failed: %s", e)
                return Response(status_code=200)
            # Create the schedule in the BACKGROUND, then refresh Home. Creating a sprint
            # schedule hits Jira (board discovery), which can exceed Slack's ~3s view-submission
            # window — doing it inline makes Slack show "trouble connecting" even on success.
            def _do_submit(cb=cb, values=values, user_id=user_id):
                try:
                    if cb == "create_delivery":
                        _submit_delivery(db, values)
                    elif cb == "create_sprint":
                        _submit_sprint(db, values)
                    elif cb == "create_dsm":
                        _submit_dsm(db, values)
                    elif cb == "create_security":
                        _submit_security(db, values)
                    elif cb == "create_sentiment":
                        _submit_sentiment(db, values)
                    elif cb == "create_portfolio":
                        _submit_portfolio(db, values)
                except Exception as e:  # noqa: BLE001
                    log.error("submission %s failed: %s", cb, e)
                publish_home(user_id)

            background_tasks.add_task(_do_submit)
            return Response(status_code=200)  # empty 200 closes the modal immediately

        return {"ok": True}

    return router


def dispatch_approved_build(approval_id: int) -> None:
    """If approval_id is an approved build:* request, enqueue its implement job from the payload.
    Safe no-op for non-build or non-approved rows."""
    row = approvals.get_request(approval_id)
    if not row or row.get("status") != "approved" or not str(row.get("action", "")).startswith("build:"):
        return
    payload = json.loads(row.get("payload") or "{}")
    queue.enqueue(
        "implement", payload,
        user_id=row.get("user_id") or "system@axelerant.com",
        dedup_key=f"implement:{approval_id}",
    )


def _val(values: dict, block_id: str) -> dict:
    return (values.get(block_id) or {}).get("v") or {}


def _submit_delivery(db, values: dict) -> None:
    selected = _val(values, "engagement").get("selected_option") or {}
    parts = (selected.get("value") or "").split("|")
    eng_id = parts[0]
    account = parts[1] if len(parts) > 1 else eng_id
    band = parts[2] if len(parts) > 2 else None
    channel = _val(values, "channel").get("selected_channel")
    frequency = (_val(values, "frequency").get("selected_option") or {}).get("value", "weekdays")
    time_str = _val(values, "time").get("selected_time", "09:00")
    if eng_id and eng_id != "none" and channel:
        service.create_delivery(db, eng_id, account, channel, frequency, time_str, band=band)


def _submit_sprint(db, values: dict) -> None:
    # The engagement select is a section accessory, so its value lives under its own
    # action_id (not the generic "v").
    selected = (values.get("engagement") or {}).get("sprint_eng_selected", {}).get("selected_option") or {}
    key = selected.get("value")
    channel = _val(values, "channel").get("selected_channel")
    time_str = _val(values, "time").get("selected_time", "17:00")
    if key and key != "none" and channel:
        service.create_sprint_report_schedule(db, key, channel, time_str)


def _submit_security(db, values: dict) -> None:
    channel = _val(values, "channel").get("selected_channel")
    frequency = (_val(values, "frequency").get("selected_option") or {}).get("value", "daily")
    time_str = _val(values, "time").get("selected_time", "09:00")
    if channel:
        service.create_security(db, channel, frequency, time_str)


def _submit_sentiment(db, values: dict) -> None:
    channel = _val(values, "channel").get("selected_channel")
    frequency = (_val(values, "frequency").get("selected_option") or {}).get("value", "weekly")
    time_str = _val(values, "time").get("selected_time", "09:00")
    if channel:
        service.create_sentiment(db, channel, frequency, time_str)


def _submit_portfolio(db, values: dict) -> None:
    channel = _val(values, "channel").get("selected_channel")
    frequency = (_val(values, "frequency").get("selected_option") or {}).get("value", "weekly")
    time_str = _val(values, "time").get("selected_time", "09:00")
    if channel:
        service.create_portfolio(db, channel, frequency, time_str)


def _submit_dsm(db, values: dict) -> None:
    channel = _val(values, "channel").get("selected_channel")
    team = (_val(values, "team").get("value") or "").strip() or (f"team-{channel}" if channel else "team")
    call_time = _val(values, "call_time").get("selected_time", "10:00")
    open_off = int((_val(values, "open_offset").get("selected_option") or {}).get("value", "120"))
    close_off = int((_val(values, "close_offset").get("selected_option") or {}).get("value", "60"))
    postcall = _val(values, "postcall_time").get("selected_time", "10:30")
    days = (_val(values, "days").get("selected_option") or {}).get("value", "weekdays")
    if channel:
        service.create_dsm(db, team, channel, call_time, open_off, close_off, postcall, days)


def _submit_standup(view: dict, user: dict) -> None:
    import json

    meta = json.loads(view.get("private_metadata") or "{}")
    team, date = meta.get("team"), meta.get("date")
    if not (team and date):
        return
    values = view.get("state", {}).get("values", {})
    standup.add_response(
        team, date, user.get("id", "unknown"),
        _val(values, "yesterday").get("value") or "",
        _val(values, "today").get("value") or "",
        _val(values, "blockers").get("value") or "",
    )
