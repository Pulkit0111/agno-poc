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

from bott.shared.observability.logging_setup import get_logger

from . import blocks, service
from .engagements import engagement_shortlist

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
            elif cmd == "run_now":
                background_tasks.add_task(run_now, user_id, action.get("value"))
            elif cmd == "remove":
                ids = [i for i in (action.get("value") or "").split(",") if i]
                service.remove(db, ids)
                background_tasks.add_task(publish_home, user_id)
            return {"ok": True}

        if ptype == "view_submission":
            cb = (payload.get("view") or {}).get("callback_id")
            values = (payload.get("view") or {}).get("state", {}).get("values", {})
            try:
                if cb == "create_delivery":
                    _submit_delivery(db, values)
                elif cb == "create_dsm":
                    _submit_dsm(db, values)
            except Exception as e:  # noqa: BLE001
                log.error("submission %s failed: %s", cb, e)
            background_tasks.add_task(publish_home, user_id)
            return Response(status_code=200)  # empty 200 closes the modal

        return {"ok": True}

    return router


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


def _submit_dsm(db, values: dict) -> None:
    channel = _val(values, "channel").get("selected_channel")
    team = (_val(values, "team").get("value") or "").strip() or (f"team-{channel}" if channel else "team")
    precall = _val(values, "precall").get("selected_time", "09:55")
    postcall = _val(values, "postcall").get("selected_time", "10:30")
    days = (_val(values, "days").get("selected_option") or {}).get("value", "weekdays")
    if channel:
        service.create_dsm(db, team, channel, precall, postcall, days)
