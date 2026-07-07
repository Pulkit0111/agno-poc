"""HMAC-signed console session tokens. Stateless: payload is base64url JSON
(email, is_admin, exp) + SHA-256 HMAC. No DB row per session; full revocation of one
already-issued token is still secret rotation (which invalidates every session at once) —
but the `is_admin` CLAIM baked in at login is re-checked live against the current
BOTT_ADMINS list on every verify, not trusted for the token's whole lifetime. Without that,
removing someone from BOTT_ADMINS didn't take effect until their week-old cookie expired on
its own. Secret comes from CONSOLE_SESSION_SECRET."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

COOKIE_NAME = "bott_console_session"
_DEFAULT_TTL = 7 * 24 * 3600.0  # one week


def _secret() -> bytes:
    return os.getenv("CONSOLE_SESSION_SECRET", "").encode()


def _sign(body: bytes) -> str:
    return hmac.new(_secret(), body, hashlib.sha256).hexdigest()


def issue_session(email: str, is_admin: bool, ttl: float = _DEFAULT_TTL) -> str:
    payload = {"email": email, "is_admin": bool(is_admin), "exp": time.time() + ttl}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{body}.{_sign(body.encode())}"


def verify_session(token: str) -> dict | None:
    if not token or "." not in token or not _secret():
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body.encode())):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:  # noqa: BLE001 — any malformed body is just an invalid token
        return None
    if payload.get("exp", 0) < time.time():
        return None
    email = payload["email"]
    is_admin = bool(payload["is_admin"])
    if is_admin:
        # Downgrade-only live re-check: if BOTT_ADMINS is configured and this email is no
        # longer in it, the admin claim baked in at login is stale — revoke it now instead
        # of waiting out the token's TTL. Never upgrades a non-admin claim, and does
        # nothing when BOTT_ADMINS is unset (nothing to check against).
        from bott.shared.config import bott_admins
        admins = bott_admins()
        if admins and email.lower() not in admins:
            is_admin = False
    return {"email": email, "is_admin": is_admin}
