"""Versioned REST layer for the web console. Handlers are THIN: they verify the
session, check scope, and delegate to existing services. No business logic here."""

from __future__ import annotations

import os
import re
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
from bott.skills import channel_map

log = get_logger("bott.console")

_STATE_COOKIE = "oidc_state"

_PROMPT_NAMES = {"identity", "voice"}


class PromptSaveBody(BaseModel):
    content: str
    note: str


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
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


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


class ReportRunBody(BaseModel):
    kind: str
    engagement: str | None = None
    channel: str | None = None
    team: str | None = None


class ModelOverrideBody(BaseModel):
    key: str
    value: str


class ConnectCodexBody(BaseModel):
    auth_json: str


class EngagementMapBody(BaseModel):
    channel_id: str
    engagement: str


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
    def run_schedule_now(request: Request, schedule_id: str, background_tasks: BackgroundTasks) -> dict:
        current_user(request)
        background_tasks.add_task(schedule_service.trigger_now, schedule_id)
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
        if not _TIME_RE.fullmatch(body.time):
            raise _err(400, "bad_time", "Time must be HH:MM in 24-hour format.")
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
        # NOTE: this Skills() instance is per-request and discarded right after — reload()
        # here would be a no-op. The single shared chat agent built once at app.py's startup
        # (the primary Slack DM/mention surface, which also serves scheduled runs) holds its
        # own long-lived Skills instance and won't see this retirement until it's rebuilt —
        # i.e. until an unrelated skill edit triggers its own reload, or the process restarts.
        # Known limitation, visible in live chat, not just scheduled runs — see the plan's
        # post-plan follow-ups.
        return {"retired": True}

    @r.post("/api/console/v1/reports/run")
    def run_report(request: Request, body: ReportRunBody) -> dict:
        current_user(request)
        if body.kind == "security":
            from bott.skills.advisories import drupal_security_advisories
            return {"result": drupal_security_advisories()}
        if body.kind == "portfolio":
            from bott.skills.portfolio.tool import get_portfolio_risk_data
            return {"result": get_portfolio_risk_data()}
        if body.kind == "sprint_snapshot":
            if not body.engagement:
                raise _err(400, "missing_field", "Pick an engagement for a sprint snapshot.")
            from bott.skills.sprint_report.tool import sprint_snapshot
            return {"result": sprint_snapshot(body.engagement)}
        if body.kind == "engagement_status":
            if not body.engagement:
                raise _err(400, "missing_field", "Pick an engagement for a status summary.")
            from bott.skills.engagement_data import get_engagement_status
            return {"result": get_engagement_status(body.engagement)}
        if body.kind == "standup_open":
            if not body.team or not body.channel:
                raise _err(400, "missing_field", "Team and channel are required to open a standup.")
            from bott.skills.dsm import open_standup
            return {"result": open_standup(body.team, body.channel)}
        if body.kind == "standup_close":
            if not body.team or not body.channel:
                raise _err(400, "missing_field", "Team and channel are required to close a standup.")
            from bott.skills.dsm import close_standup
            return {"result": close_standup(body.team, body.channel)}
        if body.kind == "standup_summary":
            if not body.team or not body.channel:
                raise _err(400, "missing_field", "Team and channel are required to post a call summary.")
            from bott.skills.dsm import post_call_summary
            return {"result": post_call_summary(body.team, body.channel)}
        raise _err(400, "bad_kind", f"Unknown report kind: {body.kind}")

    @r.get("/api/console/v1/connectors")
    def list_connectors_route(request: Request) -> dict:
        current_user(request)
        from bott.interfaces.slack_home.connectors_panel import connector_statuses
        return {"connectors": connector_statuses()}

    @r.get("/api/console/v1/models")
    def get_models(request: Request) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.interfaces.slack_home import models as models_mod
        from bott.shared.model import _review_anti_affinity
        active = models_mod._active()
        provider = active["provider"]
        conflict = active["review"] == active["build"]
        swap_preview = None
        if conflict:
            alt = _review_anti_affinity(active["review"], provider)
            swap_preview = alt if alt != active["review"] else None
        providers = []
        for name in ("codex", "openrouter", "bedrock"):
            usable, hint = models_mod.provider_key_status(name)
            providers.append({
                "name": name, "usable": usable, "hint": hint,
                "models": models_mod.available_models(name) if (usable and name == provider) else [],
            })
        return {
            "provider": provider, "chat": active["chat"], "build": active["build"],
            "review": active["review"], "conflict": conflict, "swap_preview": swap_preview,
            "providers": providers,
        }

    @r.post("/api/console/v1/models")
    def set_model_override(request: Request, body: ModelOverrideBody) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.interfaces.slack_home import models as models_mod
        message = models_mod.apply_model_override(user["email"], body.key, body.value)
        if message.startswith(("Unknown setting", "Sorry, that's not allowed")):
            raise _err(400, "override_failed", message)
        return {"message": message}

    @r.post("/api/console/v1/models/connect-codex")
    def connect_codex_route(request: Request, body: ConnectCodexBody) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.interfaces.slack_home import models as models_mod
        message = models_mod.connect_codex(user["email"], body.auth_json)
        if message.startswith(("Sorry, that's not allowed", "Couldn't read that auth.json")):
            raise _err(400, "connect_failed", message)
        return {"message": message}

    @r.get("/api/console/v1/engagements")
    def list_engagements(request: Request) -> dict:
        user = current_user(request)
        require_admin(user)
        mappings = channel_map.list_all()
        schedules = schedule_service.list_raw(db)
        counts: dict[str, int] = {}
        for sch in schedules:
            counts[sch["channel"]] = counts.get(sch["channel"], 0) + 1
        return {"engagements": [
            {**m, "schedule_count": counts.get(m["channel_id"], 0)} for m in mappings
        ]}

    @r.post("/api/console/v1/engagements")
    def map_engagement(request: Request, body: EngagementMapBody) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared.persistence.records import set_setting
        set_setting(channel_map._KEY.format(body.channel_id), body.engagement)
        return {"mapped": True}

    @r.delete("/api/console/v1/engagements/{channel_id}")
    def unmap_engagement(request: Request, channel_id: str) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared.persistence.records import set_setting
        set_setting(channel_map._KEY.format(channel_id), "")
        return {"unmapped": True}

    @r.get("/api/console/v1/users")
    def list_users(request: Request) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared.persistence import records
        admins = config.bott_admins()
        return {"users": [
            {**row, "is_admin": row["user_id"].lower() in admins}
            for row in records.list_known_users()
        ]}

    @r.get("/api/console/v1/system")
    def system_status_route(request: Request) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.interfaces.slack_home import models as models_mod
        from bott.shared import codex_tokens
        connectors = {
            "jira": config.jira_configured(),
            "confluence": config.confluence_configured(),
            "sentry": config.sentry_configured(),
            "memra": config.memra_configured(),
            "spin": config.spin_configured(),
            "google": config.google_delegation_configured(),
        }
        advisories = [
            {"name": name, "message": f"{name.capitalize()} isn't configured."}
            for name, ok in connectors.items() if not ok
        ]
        if not codex_tokens.is_connected():
            advisories.append({"name": "codex", "message": "Codex isn't connected."})
        slack_configured = bool(
            (os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")) and os.getenv("SLACK_SIGNING_SECRET")
        )
        return {
            "model": models_mod._active(),
            "database": {"kind": "postgres" if config.database_url() else "sqlite"},
            "slack_configured": slack_configured,
            "github_configured": config.github_app_configured(),
            "connectors": connectors,
            "admins_count": len(config.bott_admins()),
            "advisories": advisories,
        }

    @r.get("/api/console/v1/system/review-trends")
    def review_trends_route(request: Request, days: int = 30) -> dict:
        user = current_user(request)
        require_admin(user)
        import time
        from bott.shared.persistence import records
        since = time.time() - days * 86400
        return {"by_week": records.trace_stats_by_week(since_epoch=since)}

    @r.get("/api/console/v1/prompts/{name}")
    def get_prompt(request: Request, name: str) -> dict:
        user = current_user(request)
        require_admin(user)
        if name not in _PROMPT_NAMES:
            raise _err(400, "bad_name", f"Unknown prompt: {name}")
        from bott.agents import personality
        from bott.shared.persistence import prompts_store
        fallback = personality.IDENTITY if name == "identity" else personality.VOICE
        latest = prompts_store.latest(name)
        return {
            "current": latest["content"] if latest else fallback,
            "versions": prompts_store.list_versions(name),
        }

    @r.post("/api/console/v1/prompts/{name}")
    def save_prompt(request: Request, name: str, body: PromptSaveBody) -> dict:
        user = current_user(request)
        require_admin(user)
        if name not in _PROMPT_NAMES:
            raise _err(400, "bad_name", f"Unknown prompt: {name}")
        from bott.shared.persistence import prompts_store
        vid = prompts_store.save_version(name, body.content, body.note, user["email"], time.time())
        return {"id": vid}

    @r.post("/api/console/v1/prompts/{name}/revert/{version_id}")
    def revert_prompt(request: Request, name: str, version_id: int) -> dict:
        user = current_user(request)
        require_admin(user)
        if name not in _PROMPT_NAMES:
            raise _err(400, "bad_name", f"Unknown prompt: {name}")
        from bott.shared.persistence import prompts_store
        target = prompts_store.get_version(version_id)
        if not target or target["prompt_name"] != name:
            raise _err(404, "not_found", "That version doesn't exist.")
        vid = prompts_store.save_version(
            name, target["content"], f"Reverted to version {version_id}", user["email"], time.time())
        return {"id": vid}

    return r
