# src/bott/shared/codex_tokens.py
"""The org Codex token: one encrypted row, refreshed single-writer (rotating refresh token).

Codex is org-level — ONE shared ChatGPT subscription, not per-user. `get_valid_token()`
refreshes ahead of expiry under a Postgres advisory lock so concurrent workers never race
the single-use refresh token."""

from __future__ import annotations

import base64
import binascii
import json
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


class CodexNotConnected(RuntimeError):
    """No org Codex account is connected."""


@dataclass
class CodexToken:
    access_token: str
    account_id: str


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
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"
        ), {"u": _ORG_USER, "p": _PROVIDER}).fetchone()
    if not row:
        return None
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


def disconnect() -> None:
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE user_id=:u AND provider=:p"),
                  {"u": _ORG_USER, "p": _PROVIDER})


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
    bundle = _load_bundle()
    if bundle is None:
        raise CodexNotConnected("the org Codex account isn't connected")
    if _jwt_exp(bundle["access_token"]) - config.codex_refresh_margin_s() > time.time():
        return CodexToken(bundle["access_token"], bundle["account_id"])
    return _refresh_locked(bundle)


def _refresh_locked(bundle: dict) -> CodexToken:
    """Single-writer refresh: hold the advisory lock, re-read, refresh if still stale."""
    with get_engine().begin() as c:
        if _is_postgres():
            c.execute(text("SELECT pg_advisory_xact_lock(hashtext('codex:org'))"))
            # another worker may have refreshed while we waited — re-read inside the lock
            row = c.execute(text("SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"),
                            {"u": _ORG_USER, "p": _PROVIDER}).fetchone()
            if row:
                fresh = json.loads(SecretBox.from_env().decrypt(row[0]))
                if _jwt_exp(fresh["access_token"]) - config.codex_refresh_margin_s() > time.time():
                    return CodexToken(fresh["access_token"], fresh["account_id"])
                bundle = fresh
        try:
            new = _http_refresh(bundle["refresh_token"])
        except Exception as e:  # noqa: BLE001
            raise CodexNotConnected(f"codex token refresh failed: {redact(str(e))}") from e
        merged = {"access_token": new["access_token"],
                  "refresh_token": new.get("refresh_token", bundle["refresh_token"]),
                  "account_id": new.get("account_id", bundle["account_id"])}
        _save_bundle(c, merged)
        return CodexToken(merged["access_token"], merged["account_id"])


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
