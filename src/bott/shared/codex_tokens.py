# src/bott/shared/codex_tokens.py
"""The org Codex token: one encrypted row, refreshed single-writer (rotating refresh token).

Codex is org-level — ONE shared ChatGPT subscription, not per-user. `get_valid_token()`
refreshes ahead of expiry under a Postgres advisory lock so concurrent workers never race
the single-use refresh token."""

from __future__ import annotations

import base64
import binascii
import json
import threading
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy import text

from bott.shared import config
from bott.shared.db import get_engine
from bott.shared.observability.logging_setup import get_logger, redact
from bott.shared.secrets import SecretBox

log = get_logger("bott.codex_tokens")
_ORG_USER = "codex-org"
_PROVIDER = "codex"

NOT_CONNECTED_MSG = ("Bott isn't connected to ChatGPT — an admin needs to connect it "
                     "from the console (Models page).")


class CodexNotConnected(RuntimeError):
    """No org Codex account is connected (never connected, or its refresh token died).

    Carries status_code=401 so codex_model._provider_error marks the wrapped error
    non-retryable: no amount of retry/backoff can reconnect the org account, and the old
    default (502 → retryable) made every call on a dead login burn the full retry budget
    before surfacing anything to the user."""

    status_code = 401


@dataclass
class CodexToken:
    access_token: str
    account_id: str


# ── process-local steady-state cache ─────────────────────────────────────────
# The per-message hot path (CodexModel re-resolves the token on EVERY client access, on the
# event loop) must not pay a DB read + Fernet decrypt each time. Cache the resolved token
# briefly; keyed by the engine instance so tests that rebuild the engine
# (db.get_engine(fresh=True)) can never see a stale token from a previous database, and
# invalidated whenever the bundle is (re)stored, refreshed, or disconnected.
_CACHE_TTL_S = 30.0
_cache_lock = threading.Lock()
_cached: Optional[tuple[object, float, CodexToken]] = None
_was_connected = False  # this process has successfully loaded a bundle at least once


def _cache_get() -> Optional[CodexToken]:
    with _cache_lock:
        if _cached is None:
            return None
        engine, expires_at, tok = _cached
    if engine is not get_engine() or time.time() >= expires_at:
        return None
    return tok


def _cache_put(tok: CodexToken) -> None:
    global _cached
    # Never cache past the token's own refresh horizon — a cached token must always still
    # clear the freshness check it originally passed.
    remaining = _jwt_exp(tok.access_token) - config.codex_refresh_margin_s() - time.time()
    ttl = min(_CACHE_TTL_S, remaining)
    if ttl <= 0:
        return
    with _cache_lock:
        _cached = (get_engine(), time.time() + ttl, tok)


def _cache_clear() -> None:
    global _cached
    with _cache_lock:
        _cached = None


_ALERT_COOLDOWN_S = 3600


def _alert_disconnected(reason: str) -> None:
    """DM the admins that the shared org login is dead (at most once per hour). Entirely
    best-effort — alerting must never break the token path it is reporting on."""
    try:
        from bott.shared.alerts import alert_admins_throttled
        alert_admins_throttled(
            "codex-org-disconnected",
            f"Bott's shared Codex (ChatGPT) login is disconnected: {reason}. Every model "
            "call will fail until an admin reconnects it from the console (Models page).",
            cooldown_s=_ALERT_COOLDOWN_S,
        )
    except Exception:  # noqa: BLE001 — the alert is strictly a nice-to-have
        log.warning("codex disconnect alert failed", exc_info=True)


def _is_postgres() -> bool:
    return get_engine().url.get_backend_name().startswith("postgre")


def _jwt_exp(access_token: str) -> int:
    """Parse the `exp` claim from a JWT access token; 0 if unparseable (forces refresh)."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return 0


def _load_bundle() -> Optional[dict]:
    global _was_connected
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"
        ), {"u": _ORG_USER, "p": _PROVIDER}).fetchone()
    if not row:
        return None
    _was_connected = True
    return json.loads(SecretBox.from_env().decrypt(row[0]))


def _save_bundle(c, bundle: dict) -> None:
    ct = SecretBox.from_env().encrypt(json.dumps(bundle))
    # upsert (the table has PK (user_id, provider))
    c.execute(text("DELETE FROM connector_tokens WHERE user_id=:u AND provider=:p"),
              {"u": _ORG_USER, "p": _PROVIDER})
    c.execute(text("INSERT INTO connector_tokens(user_id,provider,token,created) "
                   "VALUES (:u,:p,:t,:c)"),
              {"u": _ORG_USER, "p": _PROVIDER, "t": ct, "c": time.time()})


def store_bundle(bundle: dict) -> None:
    for k in ("access_token", "refresh_token", "account_id"):
        if not bundle.get(k):
            raise ValueError(f"codex token bundle missing '{k}'")
    with get_engine().begin() as c:
        _save_bundle(c, {"access_token": bundle["access_token"],
                         "refresh_token": bundle["refresh_token"],
                         "account_id": bundle["account_id"]})
    _cache_clear()


def disconnect() -> None:
    global _was_connected
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE user_id=:u AND provider=:p"),
                  {"u": _ORG_USER, "p": _PROVIDER})
    _cache_clear()
    _was_connected = False  # deliberate admin action — not a "we lost the token" incident


def is_connected() -> bool:
    return _load_bundle() is not None


def _http_refresh(refresh_token: str) -> dict:
    """Exchange the rotating refresh token for a fresh bundle. Monkeypatched in tests."""
    r = httpx.post(config.codex_token_endpoint(), json={
        "grant_type": "refresh_token",
        "client_id": config.codex_client_id(),
        "refresh_token": refresh_token,
    }, timeout=30)
    r.raise_for_status()
    return r.json()


def get_valid_token() -> CodexToken:
    cached = _cache_get()
    if cached is not None:
        return cached
    bundle = _load_bundle()
    if bundle is None:
        if _was_connected:
            # We HAD a working login in this process and now the bundle is gone — that is
            # an incident (everything model-related is now failing), not a fresh install.
            _alert_disconnected("the stored token bundle is gone")
        raise CodexNotConnected(NOT_CONNECTED_MSG)
    if _jwt_exp(bundle["access_token"]) - config.codex_refresh_margin_s() > time.time():
        tok = CodexToken(bundle["access_token"], bundle["account_id"])
        _cache_put(tok)
        return tok
    return _refresh_locked(bundle)


def _refresh_locked(bundle: dict) -> CodexToken:
    """Single-writer refresh: hold the advisory lock, re-read, refresh if still stale.

    Durability invariant: the refresh token is SINGLE-USE — the moment _http_refresh
    succeeds, the old one is dead at the provider. The new bundle is therefore committed
    on its OWN connection/transaction immediately after the exchange, independent of the
    advisory-lock transaction's fate: if that outer transaction later fails or rolls back,
    it must NOT resurrect the old (now-invalid) refresh token — that would permanently
    disconnect the whole org until an admin reconnects by hand."""
    with get_engine().begin() as c:
        if _is_postgres():
            c.execute(text("SELECT pg_advisory_xact_lock(hashtext('codex:org'))"))
            # another worker may have refreshed while we waited — re-read inside the lock
            row = c.execute(text("SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"),
                            {"u": _ORG_USER, "p": _PROVIDER}).fetchone()
            if row:
                fresh = json.loads(SecretBox.from_env().decrypt(row[0]))
                if _jwt_exp(fresh["access_token"]) - config.codex_refresh_margin_s() > time.time():
                    tok = CodexToken(fresh["access_token"], fresh["account_id"])
                    _cache_put(tok)
                    return tok
                bundle = fresh
        try:
            new = _http_refresh(bundle["refresh_token"])
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if isinstance(status, int) and 400 <= status < 500:
                # The provider REJECTED the refresh token — the login is dead, not flaky.
                _alert_disconnected(f"the provider rejected the token refresh (HTTP {status})")
                raise CodexNotConnected(
                    f"{NOT_CONNECTED_MSG} (the provider rejected the token refresh: "
                    f"HTTP {status})") from e
            raise CodexNotConnected(f"codex token refresh failed: {redact(str(e))}") from e
        merged = {"access_token": new["access_token"],
                  "refresh_token": new.get("refresh_token", bundle["refresh_token"]),
                  "account_id": new.get("account_id", bundle["account_id"])}
        # Commit the rotated bundle NOW, on its own connection — see the docstring.
        with get_engine().begin() as save_c:
            _save_bundle(save_c, merged)
        tok = CodexToken(merged["access_token"], merged["account_id"])
        _cache_put(tok)
        return tok


def bootstrap_from_local(path: str = "~/.codex/auth.json") -> bool:
    """Seed the org row from a local `codex login` file (dev convenience). True if stored."""
    import os
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return False
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    toks = (data.get("tokens") or {})
    if not (toks.get("access_token") and toks.get("refresh_token") and toks.get("account_id")):
        return False
    store_bundle(toks)
    return True
