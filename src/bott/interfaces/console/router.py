"""Versioned REST layer for the web console. Handlers are THIN: they verify the
session, check scope, and delegate to existing services. No business logic here."""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from bott.interfaces.console import oidc, sessions
from bott.shared import config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.console")

_STATE_COOKIE = "oidc_state"


def _err(code: int, slug: str, message: str) -> HTTPException:
    return HTTPException(code, detail={"error": {"code": slug, "message": message}})


def _secure() -> bool:
    return os.getenv("CONSOLE_BASE_URL", "").startswith("https://")


def current_user(request: Request) -> dict:
    claims = sessions.verify_session(request.cookies.get(sessions.COOKIE_NAME, ""))
    if not claims:
        raise _err(401, "unauthenticated", "Sign in with Slack to continue.")
    return claims


def require_admin(user: dict) -> dict:
    if not user["is_admin"]:
        raise _err(403, "admin_only", "This needs an admin.")
    return user


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

    return r
