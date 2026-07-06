"""Slack OpenID Connect for the console. The email Slack returns IS Bott's
user_id (resolve_user_identity uses the same email), so login needs no mapping."""

from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.console.oidc")

_AUTHORIZE = "https://slack.com/openid/connect/authorize"
_TOKEN = "https://slack.com/api/openid.connect.token"
_USERINFO = "https://slack.com/api/openid.connect.userInfo"


def redirect_uri() -> str:
    base = os.getenv("CONSOLE_BASE_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/api/console/auth/callback"


def authorize_url(state: str) -> str:
    params = {
        "response_type": "code",
        "scope": "openid email profile",
        "client_id": os.getenv("SLACK_CLIENT_ID", ""),
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{_AUTHORIZE}?{urlencode(params)}"


def exchange_code(code: str) -> dict | None:
    """code -> access token -> userInfo. Returns {email, name} or None."""
    try:
        tok = httpx.post(_TOKEN, data={
            "client_id": os.getenv("SLACK_CLIENT_ID", ""),
            "client_secret": os.getenv("SLACK_CLIENT_SECRET", ""),
            "code": code,
            "redirect_uri": redirect_uri(),
        }, timeout=10.0).json()
        if not tok.get("ok") or not tok.get("access_token"):
            log.warning("OIDC token exchange failed: %s", tok.get("error"))
            return None
        info = httpx.get(_USERINFO, headers={
            "Authorization": f"Bearer {tok['access_token']}",
        }, timeout=10.0).json()
        email = info.get("email")
        if not info.get("ok") or not email:
            log.warning("OIDC userInfo missing email")
            return None
        return {"email": email.lower(), "name": info.get("name", "")}
    except Exception as e:  # noqa: BLE001 — auth must fail closed, never crash the app
        log.warning("OIDC exchange error: %s", e)
        return None
