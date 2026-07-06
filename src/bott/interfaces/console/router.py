"""Versioned REST layer for the web console. Handlers are THIN: they verify the
session, check scope, and delegate to existing services. No business logic here."""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from bott.interfaces.console import oidc, sessions
from bott.shared import approvals, config
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import queue

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


def build_console_router() -> APIRouter:
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
    def logout() -> JSONResponse:
        resp = JSONResponse({"ok": True})
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
        approvals.decide(approval_id, approved=body.approve, decided_by=user["email"])
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

    return r
