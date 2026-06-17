"""AgentOS HTTP front door for Bott — the control-plane API the dashboard consumes.

Serves the same manager team + code-review agent as Slack, backed by the SAME SqliteDb
(agentos.db). Runs as a separate process from the Slack server.

Auth: when AGENT_OS_JWT_SECRET is set, a JWTMiddleware validates a short-lived HS256
token minted by the Next.js BFF (the only legitimate caller). When unset, the API runs
open — local dev only.

Run:  agentos-server   (or: python -m bott.interfaces.agentos)
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

import httpx
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from fastapi import APIRouter
from pydantic import BaseModel

from bott.manager.manager import apply_manager_model, build_manager, effective_manager_model
from bott.shared.config import DEFAULT_MODEL as _REVIEW_DEFAULT
from bott.shared.config import (
    FALLBACK_CODEX_MODELS,
    SETTING_MANAGER_MODEL,
    SETTING_REVIEWER_MODEL,
    agentos_db_path,
    agentos_jwt_secret,
    manager_base_url,
)
from bott.shared.persistence import store

_db = SqliteDb(db_file=agentos_db_path())
_team = build_manager(db=_db)
_code_review = _team.members[0]

agent_os = AgentOS(
    id="bott-os",
    name="Bott OS",
    description="Bott — a conversational engineering teammate.",
    agents=[_code_review],
    teams=[_team],
    db=_db,
    telemetry=False,
)
app = agent_os.get_app()


# ── Bott model-selection API (consumed by the dashboard Settings page) ──────────
def _available_models() -> list[str]:
    """Models the Codex proxy exposes (live), falling back to a curated list. We query
    the manager's base_url since both roles share the same Codex proxy."""
    base = manager_base_url()
    if base:
        try:
            resp = httpx.get(f"{base.rstrip('/')}/models", timeout=4.0)
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json().get("data", []) if m.get("id")]
            if ids:
                return sorted(ids)
        except Exception:
            pass
    return list(FALLBACK_CODEX_MODELS)


class SettingsBody(BaseModel):
    manager_model: str | None = None
    reviewer_model: str | None = None


_bott_router = APIRouter(prefix="/bott", tags=["bott"])


@_bott_router.get("/models")
def get_models() -> dict:
    return {
        "models": _available_models(),
        "manager_model": effective_manager_model(),
        "reviewer_model": store.get_setting(SETTING_REVIEWER_MODEL) or _REVIEW_DEFAULT,
    }


@_bott_router.get("/settings")
def get_settings() -> dict:
    return {
        "manager_model": effective_manager_model(),
        "reviewer_model": store.get_setting(SETTING_REVIEWER_MODEL) or _REVIEW_DEFAULT,
    }


@_bott_router.post("/settings")
def post_settings(body: SettingsBody) -> dict:
    if body.manager_model:
        store.set_setting(SETTING_MANAGER_MODEL, body.manager_model)
        # Apply to the live team so dashboard chat uses it on the next run.
        apply_manager_model(_team, body.manager_model)
    if body.reviewer_model:
        store.set_setting(SETTING_REVIEWER_MODEL, body.reviewer_model)
    return get_settings()


app.include_router(_bott_router)

_secret = agentos_jwt_secret()
if _secret:
    from agno.os.middleware import JWTMiddleware

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[_secret],
        algorithm="HS256",
        validate=True,
        user_id_claim="sub",
        dependencies_claims=["email", "name", "hd"],
        # /health, /docs, /openapi.json, etc. stay public by JWTMiddleware default.
    )


def main() -> None:
    agent_os.serve(
        app="bott.interfaces.agentos:app",
        host=os.getenv("AGENTOS_HOST", "localhost"),
        port=int(os.getenv("AGENTOS_PORT", "7777")),
    )


if __name__ == "__main__":
    main()
