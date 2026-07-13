"""HMAC-signed console session tokens. Stateless: payload is base64url JSON
(email, is_admin, exp) + SHA-256 HMAC. No DB row per session; full revocation of one
already-issued token is still secret rotation (which invalidates every session at once) —
but the `is_admin` CLAIM baked into the payload at login is never trusted directly: every
verify recomputes it live from `bott.shared.roles.is_admin` (env BOTT_ADMINS union KV-stored
roles), in both directions. That cuts both ways on purpose — removing someone from
BOTT_ADMINS (or demoting them via the console) revokes access on their very next request
instead of waiting out the cookie's up-to-7-day TTL, AND promoting a member via the console
takes effect on their next request too, without forcing a re-login. The email itself stays
HMAC-verified; only the privilege attached to it is re-derived every time. Secret comes from
CONSOLE_SESSION_SECRET."""

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
    # The payload's own `is_admin` claim is ignored here — it's advisory only. The real
    # answer is recomputed live from roles.is_admin (env ∪ KV) on every single verify, so
    # neither a stale downgrade nor a stale "not yet promoted" claim can outlive the
    # cookie's TTL.
    from bott.shared import roles
    is_admin = roles.is_admin(email)
    return {"email": email, "is_admin": is_admin}
