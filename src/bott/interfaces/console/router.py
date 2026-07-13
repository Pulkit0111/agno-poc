"""Versioned REST layer for the web console. Handlers are THIN: they verify the
session, check scope, and delegate to existing services. No business logic here."""

from __future__ import annotations

import os
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from bott.interfaces.console import oidc, sessions
from bott.interfaces.slack_home import service as schedule_service
from bott.shared import action_policy, approvals, config
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


def _jobs_summary() -> dict:
    """Console-facing job tallies derived from the queue's raw status counts. The queue
    uses 'pending'/'running'/'done'/'failed'; 'pending' surfaces as 'queued' here. Shared
    by the /jobs/counts and /health endpoints so they can't drift."""
    counts = queue.job_counts()
    return {
        "running": counts.get("running", 0),
        "queued": counts.get("pending", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "failed_24h": queue.count_failed_since(time.time() - 86400),
    }


def _secure() -> bool:
    return os.getenv("CONSOLE_BASE_URL", "").startswith("https://")


def should_mount_console() -> bool:
    """Console mounts only when a session secret exists — no secret, no cookies."""
    return bool(os.getenv("CONSOLE_SESSION_SECRET"))


_CONSOLE_INTENT_VARS = ("SLACK_CLIENT_ID", "CONSOLE_BASE_URL")


def require_console_env() -> None:
    """Fail LOUD at startup on a half-configured console. Console-intent vars present
    without a session secret means the console UI would just 404 with only a log line to
    explain why. A Slack-only install (no console vars at all) stays valid — skip mounting."""
    if os.getenv("CONSOLE_SESSION_SECRET"):
        return
    present = [v for v in _CONSOLE_INTENT_VARS if os.getenv(v)]
    if present:
        raise RuntimeError(
            f"CONSOLE_SESSION_SECRET is not set, but {' and '.join(present)} "
            "indicate the web console is intended. Set CONSOLE_SESSION_SECRET to a long "
            "random string (the console API cannot sign session cookies without it), "
            "or unset the console vars for a Slack-only install."
        )


_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _origin_tuple(url: str) -> tuple[str, str, int | None]:
    """(scheme, host, effective port) for origin comparison — default ports normalized."""
    p = urlsplit(url)
    scheme = p.scheme.lower()
    port = p.port or {"https": 443, "http": 80}.get(scheme)
    return (scheme, (p.hostname or "").lower(), port)


def csrf_guard(request: Request) -> None:
    """CSRF defence for the cookie-authed console (session cookie is SameSite=Lax, which
    still permits cross-site top-level POST navigations). Browsers always attach `Origin`
    to cross-origin mutating requests, so a mismatch against CONSOLE_BASE_URL's origin is
    rejected; `Referer` is the fallback signal. Requests carrying NEITHER header (curl,
    server-to-server clients with a valid session cookie) are allowed through."""
    if request.method in _CSRF_SAFE_METHODS:
        return
    expected = _origin_tuple(os.getenv("CONSOLE_BASE_URL", "http://localhost:3000"))
    origin = request.headers.get("origin")
    if origin:
        if _origin_tuple(origin) != expected:
            raise _err(403, "bad_origin", "Cross-origin request rejected.")
        return
    referer = request.headers.get("referer")
    if referer and _origin_tuple(referer) != expected:
        raise _err(403, "bad_origin", "Cross-origin request rejected.")


def current_user(request: Request) -> dict:
    claims = sessions.verify_session(request.cookies.get(sessions.COOKIE_NAME, ""))
    if not claims:
        raise _err(401, "unauthenticated", "Sign in with Slack to continue.")
    return claims


def require_admin(user: dict) -> dict:
    if not user["is_admin"]:
        raise _err(403, "admin_only", "This needs an admin.")
    return user


def _dispatch_build(approval_id: int) -> int | None:
    from bott.interfaces.slack_home.router import dispatch_approved_build
    return dispatch_approved_build(approval_id)


def _dispatch_api(approval_id: int) -> None:
    from bott.skills.connectors.actions import dispatch_approved_api
    dispatch_approved_api(approval_id)


class DecisionBody(BaseModel):
    approve: bool


_VALID_FREQUENCIES = {"daily", "weekdays", "weekly"}
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_VALID_SYSTEMS = {"slack", "github", "atlassian", "http"}


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
    team: str | None = None


class SchedulePreviewBody(BaseModel):
    kind: str
    frequency: str
    time: str


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


class PolicyOverrideBody(BaseModel):
    system: str
    method: str
    verdict: str
    reason: str


class ClassifyBody(BaseModel):
    system: str
    method: str


def build_console_router(db) -> APIRouter:
    # csrf_guard runs on EVERY console route (it no-ops on safe methods) so no future
    # mutating endpoint can be added without CSRF protection.
    r = APIRouter(dependencies=[Depends(csrf_guard)])

    def require_schedule_owner_or_admin(schedule_id: str, user: dict) -> None:
        """Owner-or-admin gate for schedule mutations: admins pass unconditionally;
        everyone else must be the schedule's stamped (or legacy-inferred) creator. A
        schedule with no recoverable owner (created before `created_by` existed, or
        already deleted) is admin-only — never assume a member owns an unattributed row."""
        if user["is_admin"]:
            return
        owner = schedule_service.schedule_owner_for_id(db, schedule_id)
        if not owner or owner.lower() != user["email"].lower():
            raise _err(403, "not_owner", "Only this schedule's creator or an admin can do this.")

    @r.get("/api/console/auth/login")
    def login() -> RedirectResponse:
        state = secrets.token_urlsafe(16)
        resp = RedirectResponse(oidc.authorize_url(state), status_code=307)
        resp.set_cookie(_STATE_COOKIE, state, httponly=True, samesite="lax",
                        secure=_secure(), max_age=600)
        return resp

    @r.get("/api/console/auth/callback")
    def callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
        base = os.getenv("CONSOLE_BASE_URL", "http://localhost:3000").rstrip("/")

        def _login_error(slug: str) -> RedirectResponse:
            # Bounce back to the styled login page with a slug the frontend renders,
            # instead of surfacing a raw JSON error page. State cookie is cleared either way.
            resp = RedirectResponse(f"{base}/login?error={slug}", status_code=307)
            resp.delete_cookie(_STATE_COOKIE)
            return resp

        if not state or state != request.cookies.get(_STATE_COOKIE):
            return _login_error("bad_state")
        info = oidc.exchange_code(code)
        if not info:
            return _login_error("oidc_failed")
        domain = info["email"].rsplit("@", 1)[-1].lower()
        if domain != config.allowed_email_domain().lower():
            log.warning("console login rejected — wrong domain: %s", info["email"])
            return _login_error("wrong_domain")
        is_admin = info["email"] in config.bott_admins()
        token = sessions.issue_session(info["email"], is_admin)
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

    @r.get("/api/console/v1/approvals/count")
    def approvals_count(request: Request) -> dict:
        require_admin(current_user(request))
        return {"pending": approvals.pending_count()}

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
        # DECIDING is admin-only — a requester approving their own request would defeat
        # the human-sign-off gate. (Viewing stays requester-or-admin; admins MAY approve
        # their own requests so single-admin orgs don't deadlock.)
        if not user["is_admin"]:
            raise _err(403, "admin_only", "Only an admin can decide approvals.")
        row = approvals.get_request(approval_id)
        if not row:
            raise _err(404, "not_found", "That approval doesn't exist.")
        if row["status"] != "pending":
            raise _err(409, "already_decided", f"Already {row['status']}.")
        if not approvals.decide(approval_id, approved=body.approve, decided_by=user["email"]):
            raise _err(409, "already_decided", "Someone else just decided this.")
        action = str(row.get("action", ""))
        job_id: int | None = None
        if body.approve:
            if action.startswith(("build:", "triage:")):
                # build/triage dispatch is synchronous, so the implement job id is available
                # here — link the frontend straight to the run. (api:* dispatch runs in a
                # background task and produces no queued job, so it has no id to return.)
                job_id = _dispatch_build(approval_id)
            elif action.startswith("api:"):
                background_tasks.add_task(_dispatch_api, approval_id)
        resp = {"status": "approved" if body.approve else "dismissed"}
        if job_id is not None:
            resp["job_id"] = job_id
        return resp

    @r.get("/api/console/v1/jobs")
    def list_jobs(request: Request, scope: str = "mine", limit: int = 25) -> dict:
        user = current_user(request)
        limit = max(1, min(limit, 100))
        if scope == "all":
            require_admin(user)
            return {"jobs": queue.recent_jobs(limit=limit)}
        return {"jobs": queue.recent_jobs_for(user["email"], limit=limit)}

    @r.get("/api/console/v1/jobs/counts")
    def jobs_counts(request: Request) -> dict:
        require_admin(current_user(request))
        return _jobs_summary()

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
        require_schedule_owner_or_admin(schedule_id, current_user(request))
        if not schedule_service.pause(db, schedule_id):
            raise _err(404, "not_found", "That schedule doesn't exist.")
        return {"enabled": False}

    @r.post("/api/console/v1/schedules/{schedule_id}/resume")
    def resume_schedule(request: Request, schedule_id: str) -> dict:
        require_schedule_owner_or_admin(schedule_id, current_user(request))
        if not schedule_service.resume(db, schedule_id):
            raise _err(404, "not_found", "That schedule doesn't exist.")
        return {"enabled": True}

    @r.post("/api/console/v1/schedules/{schedule_id}/run-now")
    def run_schedule_now(request: Request, schedule_id: str, background_tasks: BackgroundTasks) -> dict:
        require_schedule_owner_or_admin(schedule_id, current_user(request))
        background_tasks.add_task(schedule_service.trigger_now, schedule_id)
        return {"triggered": True}

    @r.delete("/api/console/v1/schedules/{schedule_id}")
    def delete_schedule(request: Request, schedule_id: str) -> dict:
        require_schedule_owner_or_admin(schedule_id, current_user(request))
        schedule_service.remove(db, [schedule_id])
        return {"deleted": True}

    @r.post("/api/console/v1/schedules")
    def create_schedule(request: Request, body: ScheduleCreateBody) -> dict:
        user = current_user(request)
        if body.frequency is not None and body.frequency not in _VALID_FREQUENCIES:
            raise _err(400, "bad_frequency", f"Unknown cadence: {body.frequency}")
        if not _TIME_RE.fullmatch(body.time):
            raise _err(400, "bad_time", "Time must be HH:MM in 24-hour format.")
        if body.kind == "sprint":
            if not body.engagement:
                raise _err(400, "missing_field", "Pick an engagement for a sprint report schedule.")
            sch = schedule_service.create_sprint_report_schedule(
                db, body.engagement, body.channel, body.time, created_by=user["email"])
        elif body.kind == "delivery":
            if not body.engagement or not body.frequency:
                raise _err(400, "missing_field", "Pick an engagement and a cadence for a delivery digest.")
            sch = schedule_service.create_delivery(
                db, body.engagement, body.account_name or "", body.channel, body.frequency, body.time,
                band=body.band, created_by=user["email"])
        elif body.kind == "security":
            if not body.frequency:
                raise _err(400, "missing_field", "Pick a cadence for the security digest.")
            sch = schedule_service.create_security(db, body.channel, body.frequency, body.time,
                                                   created_by=user["email"])
        elif body.kind == "sentiment":
            if not body.frequency:
                raise _err(400, "missing_field", "Pick a cadence for the sentiment report.")
            sch = schedule_service.create_sentiment(db, body.channel, body.frequency, body.time,
                                                    created_by=user["email"])
        elif body.kind == "portfolio":
            if not body.frequency:
                raise _err(400, "missing_field", "Pick a cadence for the portfolio dashboard.")
            sch = schedule_service.create_portfolio(db, body.channel, body.frequency, body.time,
                                                     created_by=user["email"])
        elif body.kind == "dsm":
            team = (body.team or "").strip()
            if not team or not body.channel:
                raise _err(400, "missing_field", "Pick a team and a channel for a DSM schedule.")
            sch = schedule_service.create_dsm_default(
                db, team, body.channel, body.time, days=body.frequency or "weekdays",
                created_by=user["email"])
        else:
            raise _err(400, "bad_kind", f"Unknown schedule kind: {body.kind}")
        return {"id": sch.id}

    @r.post("/api/console/v1/schedules/preview")
    def preview_schedule(request: Request, body: SchedulePreviewBody) -> dict:
        current_user(request)
        if body.frequency not in _VALID_FREQUENCIES:
            raise _err(400, "bad_frequency", f"Unknown cadence: {body.frequency}")
        if not _TIME_RE.fullmatch(body.time):
            raise _err(400, "bad_time", "Time must be HH:MM in 24-hour format.")
        return schedule_service.preview(body.frequency, body.time)

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
        require_admin(current_user(request))
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
        from bott.interfaces.slack_home import models as models_mod
        from bott.shared.model import _review_anti_affinity
        active = models_mod._active()
        if not user["is_admin"]:
            # Members get the task->model matrix (ids only, for the Home-page model card)
            # plus just enough for the "is Codex connected" banner. No key hints, no
            # usage, no model catalog.
            usable, _hint = models_mod.provider_key_status("codex")
            return {
                "active": active,
                "providers": [{"name": "codex", "usable": usable, "hint": None, "models": []}],
            }
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
        codex_usage = None
        if any(p["name"] == "codex" and p["usable"] for p in providers):
            from bott.shared.codex_usage import usage_summary
            try:
                codex_usage = usage_summary()
            except Exception as e:  # noqa: BLE001 — usage visibility is a nice-to-have
                log.warning("codex usage_summary failed: %s", e)
        return {
            "provider": provider, "chat": active["chat"], "build": active["build"],
            "review": active["review"], "conflict": conflict, "swap_preview": swap_preview,
            "providers": providers, "codex_usage": codex_usage,
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

    # ── Connect ChatGPT (device-auth) ────────────────────────────────────────────────
    # Preferred over the paste-JSON flow above: click Connect, get a URL + code, approve
    # in a browser, and this flips to connected on its own — no manual auth.json copying.
    # Falls back to needing the `codex` CLI installed on whatever host runs the console API
    # (not every worker — inference itself never shells out to the CLI).

    @r.post("/api/console/v1/models/codex-login/start")
    def start_codex_login_route(request: Request) -> dict:
        require_admin(current_user(request))
        from bott.shared.codex_login import start_codex_login
        result = start_codex_login()
        if "error" in result:
            raise _err(400, "codex_login_failed", result["error"])
        return result

    @r.get("/api/console/v1/models/codex-login/status")
    def codex_login_status_route(request: Request) -> dict:
        require_admin(current_user(request))
        from bott.shared.codex_login import codex_login_status
        return codex_login_status()

    @r.post("/api/console/v1/models/codex-login/disconnect")
    def disconnect_codex_login_route(request: Request) -> dict:
        require_admin(current_user(request))
        from bott.shared.codex_login import disconnect_codex_login
        disconnect_codex_login()
        return {"connected": False}

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

    @r.get("/api/console/v1/health")
    def health_route(request: Request) -> dict:
        require_admin(current_user(request))
        from bott.interfaces.slack_home import models as models_mod
        from bott.interfaces.slack_home.connectors_panel import connector_statuses
        from bott.shared import codex_tokens
        from bott.shared.persistence import records
        jobs = _jobs_summary()
        raw = records.get_setting("webhook.github.last_received_at")
        last_received_at = float(raw) if raw else None
        return {
            "model": {
                "connected": codex_tokens.is_connected(),
                "provider": models_mod._active()["provider"],
            },
            "jobs": {"running": jobs["running"], "queued": jobs["queued"],
                     "failed_24h": jobs["failed_24h"]},
            "connectors": connector_statuses(),
            "webhook": {"last_received_at": last_received_at},
        }

    @r.get("/api/console/v1/reviews")
    def list_reviews_route(request: Request) -> dict:
        require_admin(current_user(request))
        from bott.shared.persistence import records
        return {"reviews": records.recent_reviews(limit=50)}

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

    @r.get("/api/console/v1/policy/overrides")
    def list_policy_overrides(request: Request) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared import policy_overrides
        return {"overrides": policy_overrides.list_overrides()}

    @r.post("/api/console/v1/policy/overrides")
    def set_policy_override(request: Request, body: PolicyOverrideBody) -> dict:
        user = current_user(request)
        require_admin(user)
        if body.system not in _VALID_SYSTEMS:
            raise _err(400, "bad_system", f"Unknown system: {body.system}")
        if body.verdict not in ("allow", "gate", "deny"):
            raise _err(400, "bad_verdict", f"Unknown verdict: {body.verdict}")
        from bott.shared import policy_overrides
        policy_overrides.set_override(body.system, body.method, body.verdict, body.reason, user["email"])
        return {"set": True}

    @r.delete("/api/console/v1/policy/overrides/{system}/{method}")
    def remove_policy_override(request: Request, system: str, method: str) -> dict:
        user = current_user(request)
        require_admin(user)
        from bott.shared import policy_overrides
        policy_overrides.remove_override(system, method)
        return {"removed": True}

    @r.post("/api/console/v1/policy/classify")
    def classify_route(request: Request, body: ClassifyBody) -> dict:
        user = current_user(request)
        require_admin(user)
        decision = action_policy.classify(body.system, body.method)
        return {"verdict": decision.verdict, "reason": decision.reason}

    @r.get("/api/console/v1/policy/repos")
    def list_allowed_repos(request: Request) -> dict:
        user = current_user(request)
        require_admin(user)
        return {"repos": sorted(config.allowed_post_repos())}

    return r
