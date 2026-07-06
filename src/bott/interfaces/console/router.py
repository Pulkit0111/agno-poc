"""Versioned REST layer for the web console. Handlers are THIN: they verify the
session, check scope, and delegate to existing services. No business logic here."""

from __future__ import annotations

import os
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from bott.interfaces.console import oidc, sessions
from bott.interfaces.slack_home import service as schedule_service
from bott.shared import approvals, config
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import action_items, queue

log = get_logger("bott.console")

_STATE_COOKIE = "oidc_state"


def _err(code: int, slug: str, message: str) -> HTTPException:
    return HTTPException(code, detail={"error": {"code": slug, "message": message}})


def _secure() -> bool:
    return os.getenv("CONSOLE_BASE_URL", "").startswith("https://")


def should_mount_console() -> bool:
    """Console mounts only when a session secret exists — no secret, no cookies."""
    return bool(os.getenv("CONSOLE_SESSION_SECRET"))


def current_user(request: Request) -> dict:
    claims = sessions.verify_session(request.cookies.get(sessions.COOKIE_NAME, ""))
    if not claims:
        raise _err(401, "unauthenticated", "Sign in with Slack to continue.")
    return claims


def require_admin(user: dict) -> dict:
    if not user["is_admin"]:
        raise _err(403, "admin_only", "This needs an admin.")
    return user


def _dispatch_build(approval_id: int) -> None:
    from bott.interfaces.slack_home.router import dispatch_approved_build
    dispatch_approved_build(approval_id)


def _dispatch_api(approval_id: int) -> None:
    from bott.skills.connectors.actions import dispatch_approved_api
    dispatch_approved_api(approval_id)


class DecisionBody(BaseModel):
    approve: bool


_VALID_FREQUENCIES = {"daily", "weekdays", "weekly"}


class SnoozeBody(BaseModel):
    remind_at: float | None = None


class ScheduleCreateBody(BaseModel):
    kind: str
    channel: str
    time: str
    frequency: str | None = None
    engagement: str | None = None
    account_name: str | None = None
    band: str | None = None


def _skills():
    from agno.skills import LocalSkills, Skills
    from bott.shared import config
    return Skills(loaders=[LocalSkills(config.bott_skills_dir())])


class PinBody(BaseModel):
    pinned: bool


def build_console_router(db) -> APIRouter:
    r = APIRouter()

    @r.get("/api/console/auth/login")
    def login() -> RedirectResponse:
        state = secrets.token_urlsafe(16)
        resp = RedirectResponse(oidc.authorize_url(state), status_code=307)
        resp.set_cookie(_STATE_COOKIE, state, httponly=True, samesite="lax",
                        secure=_secure(), max_age=600)
        return resp

    @r.get("/api/console/auth/callback")
    def callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
        if not state or state != request.cookies.get(_STATE_COOKIE):
            raise _err(400, "bad_state", "Login flow expired — try again.")
        info = oidc.exchange_code(code)
        if not info:
            raise _err(401, "oidc_failed", "Slack sign-in failed — try again.")
        is_admin = info["email"] in config.bott_admins()
        token = sessions.issue_session(info["email"], is_admin)
        base = os.getenv("CONSOLE_BASE_URL", "http://localhost:3000").rstrip("/")
        resp = RedirectResponse(f"{base}/", status_code=307)
        resp.delete_cookie(_STATE_COOKIE)
        resp.set_cookie(sessions.COOKIE_NAME, token, httponly=True, samesite="lax",
                        secure=_secure(), max_age=7 * 24 * 3600)
        log.info("console login: %s (admin=%s)", info["email"], is_admin)
        return resp

    @r.post("/api/console/auth/logout")
    def logout() -> RedirectResponse:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(sessions.COOKIE_NAME)
        return resp

    @r.get("/api/console/v1/me")
    def me(request: Request) -> dict:
        return current_user(request)

    @r.get("/api/console/v1/approvals")
    def list_approvals(request: Request, scope: str = "mine") -> dict:
        user = current_user(request)
        if scope == "all":
            require_admin(user)
            return {"approvals": approvals.pending_all(limit=50)}
        rows = approvals.pending_for(user["email"], limit=50)
        return {"approvals": [dict(row, user_id=user["email"]) for row in rows]}

    @r.get("/api/console/v1/approvals/{approval_id}")
    def approval_detail(request: Request, approval_id: int) -> dict:
        user = current_user(request)
        row = approvals.get_request(approval_id)
        if not row:
            raise _err(404, "not_found", "That approval doesn't exist.")
        if row["user_id"] != user["email"] and not user["is_admin"]:
            raise _err(403, "not_yours", "Only the requester or an admin can view this.")
        return row

    @r.post("/api/console/v1/approvals/{approval_id}/decision")
    def decide_approval(request: Request, approval_id: int, body: DecisionBody,
                        background_tasks: BackgroundTasks) -> dict:
        user = current_user(request)
        row = approvals.get_request(approval_id)
        if not row:
            raise _err(404, "not_found", "That approval doesn't exist.")
        if row["user_id"] != user["email"] and not user["is_admin"]:
            raise _err(403, "not_yours", "Only the requester or an admin can decide this.")
        if row["status"] != "pending":
            raise _err(409, "already_decided", f"Already {row['status']}.")
        if not approvals.decide(approval_id, approved=body.approve, decided_by=user["email"]):
            raise _err(409, "already_decided", "Someone else just decided this.")
        action = str(row.get("action", ""))
        if body.approve:
            if action.startswith(("build:", "triage:")):
                _dispatch_build(approval_id)
            elif action.startswith("api:"):
                background_tasks.add_task(_dispatch_api, approval_id)
        return {"status": "approved" if body.approve else "dismissed"}

    @r.get("/api/console/v1/jobs")
    def list_jobs(request: Request, scope: str = "mine", limit: int = 25) -> dict:
        user = current_user(request)
        limit = max(1, min(limit, 100))
        if scope == "all":
            require_admin(user)
            return {"jobs": queue.recent_jobs(limit=limit)}
        return {"jobs": queue.recent_jobs_for(user["email"], limit=limit)}

    @r.get("/api/console/v1/jobs/{job_id}")
    def job_detail_route(request: Request, job_id: int) -> dict:
        user = current_user(request)
        row = queue.job_detail(job_id)
        if not row:
            raise _err(404, "not_found", "That run doesn't exist.")
        if row["user_id"] != user["email"] and not user["is_admin"]:
            raise _err(403, "not_yours", "Only the requester or an admin can view this run.")
        return row

    @r.get("/api/console/v1/schedules")
    def list_schedules(request: Request) -> dict:
        current_user(request)
        return {"schedules": schedule_service.list_raw(db)}

    @r.post("/api/console/v1/schedules/{schedule_id}/pause")
    def pause_schedule(request: Request, schedule_id: str) -> dict:
        current_user(request)
        if not schedule_service.pause(db, schedule_id):
            raise _err(404, "not_found", "That schedule doesn't exist.")
        return {"enabled": False}

    @r.post("/api/console/v1/schedules/{schedule_id}/resume")
    def resume_schedule(request: Request, schedule_id: str) -> dict:
        current_user(request)
        if not schedule_service.resume(db, schedule_id):
            raise _err(404, "not_found", "That schedule doesn't exist.")
        return {"enabled": True}

    @r.post("/api/console/v1/schedules/{schedule_id}/run-now")
    def run_schedule_now(request: Request, schedule_id: str) -> dict:
        current_user(request)
        schedule_service.trigger_now(schedule_id)
        return {"triggered": True}

    @r.delete("/api/console/v1/schedules/{schedule_id}")
    def delete_schedule(request: Request, schedule_id: str) -> dict:
        current_user(request)
        schedule_service.remove(db, [schedule_id])
        return {"deleted": True}

    @r.post("/api/console/v1/schedules")
    def create_schedule(request: Request, body: ScheduleCreateBody) -> dict:
        current_user(request)
        if body.frequency is not None and body.frequency not in _VALID_FREQUENCIES:
            raise _err(400, "bad_frequency", f"Unknown cadence: {body.frequency}")
        if body.kind == "sprint":
            if not body.engagement:
                raise _err(400, "missing_field", "Pick an engagement for a sprint report schedule.")
            sch = schedule_service.create_sprint_report_schedule(db, body.engagement, body.channel, body.time)
        elif body.kind == "delivery":
            if not body.engagement or not body.frequency:
                raise _err(400, "missing_field", "Pick an engagement and a cadence for a delivery digest.")
            sch = schedule_service.create_delivery(
                db, body.engagement, body.account_name or "", body.channel, body.frequency, body.time, band=body.band)
        elif body.kind == "security":
            if not body.frequency:
                raise _err(400, "missing_field", "Pick a cadence for the security digest.")
            sch = schedule_service.create_security(db, body.channel, body.frequency, body.time)
        elif body.kind == "sentiment":
            if not body.frequency:
                raise _err(400, "missing_field", "Pick a cadence for the sentiment report.")
            sch = schedule_service.create_sentiment(db, body.channel, body.frequency, body.time)
        elif body.kind == "portfolio":
            if not body.frequency:
                raise _err(400, "missing_field", "Pick a cadence for the portfolio dashboard.")
            sch = schedule_service.create_portfolio(db, body.channel, body.frequency, body.time)
        else:
            raise _err(400, "bad_kind", f"Unknown schedule kind: {body.kind}")
        return {"id": sch.id}

    @r.get("/api/console/v1/action-items")
    def list_action_items(request: Request, include_done: bool = False) -> dict:
        user = current_user(request)
        return {"items": action_items.list_items(user["email"], include_done=include_done)}

    @r.post("/api/console/v1/action-items/{item_id}/done")
    def complete_action_item(request: Request, item_id: int) -> dict:
        user = current_user(request)
        if not action_items.complete_item(user["email"], item_id, time.time()):
            raise _err(404, "not_found", "That action item doesn't exist or isn't yours.")
        return {"status": "done"}

    @r.post("/api/console/v1/action-items/{item_id}/snooze")
    def snooze_action_item(request: Request, item_id: int, body: SnoozeBody) -> dict:
        user = current_user(request)
        now = time.time()
        remind_at = body.remind_at if body.remind_at is not None else now + 86400
        if not action_items.snooze_item(user["email"], item_id, remind_at, now):
            raise _err(404, "not_found", "That action item doesn't exist or isn't yours.")
        return {"status": "snoozed", "remind_at": remind_at}

    @r.get("/api/console/v1/skills")
    def list_skills_route(request: Request) -> dict:
        current_user(request)
        from bott.shared.persistence import skills_store
        sk = _skills()
        rows = []
        for name in sk.get_skill_names():
            skill = sk.get_skill(name)
            row = skill.to_dict()
            db_row = skills_store.get_skill(name)
            row["built_in"] = db_row is None
            row["pinned"] = bool(db_row["pinned"]) if db_row else False
            row["authored_by"] = db_row["authored_by"] if db_row else None
            rows.append(row)
        return {"skills": rows}

    @r.get("/api/console/v1/skills/{slug}")
    def skill_detail_route(request: Request, slug: str) -> dict:
        current_user(request)
        from bott.shared.persistence import skills_store
        sk = _skills()
        skill = sk.get_skill(slug)
        if not skill:
            raise _err(404, "not_found", "That skill doesn't exist.")
        row = skill.to_dict()
        db_row = skills_store.get_skill(slug)
        row["built_in"] = db_row is None
        row["pinned"] = bool(db_row["pinned"]) if db_row else False
        row["authored_by"] = db_row["authored_by"] if db_row else None
        return row

    @r.post("/api/console/v1/skills/{slug}/pin")
    def pin_skill_route(request: Request, slug: str, body: PinBody) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared.persistence import skills_store
        if not skills_store.set_pinned(slug, body.pinned):
            raise _err(404, "not_found", "That skill doesn't exist or isn't authored — built-ins can't be pinned.")
        return {"pinned": body.pinned}

    @r.post("/api/console/v1/skills/{slug}/retire")
    def retire_skill_route(request: Request, slug: str) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared.persistence import skills_store
        sk = _skills()
        if slug in sk.get_skill_names() and skills_store.get_skill(slug) is None:
            raise _err(400, "builtin_protected", "Built-in skills can't be retired.")
        db_row = skills_store.get_skill(slug)
        if db_row and db_row.get("pinned"):
            raise _err(400, "pinned_protected", "Unpin this skill before retiring it.")
        if not skills_store.delete_skill(slug):
            raise _err(404, "not_found", "That skill doesn't exist.")
        import shutil
        from bott.shared import config
        shutil.rmtree(f"{config.bott_skills_dir()}/{slug}", ignore_errors=True)
        sk.reload()
        return {"retired": True}

    return r
